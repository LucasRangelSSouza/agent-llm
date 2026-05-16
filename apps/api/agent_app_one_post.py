from fastapi import FastAPI, Request, UploadFile, File, Form, HTTPException, Header, APIRouter
from fastapi.responses import JSONResponse
from fastapi.encoders import jsonable_encoder
from fastapi.middleware.cors import CORSMiddleware
from agent.engine.agent_loader import AgentLoader
from agent.modules.agents.master_orchestrator_agent import MasterOrchestratorAgent
from typing import Optional, List, AsyncGenerator
from fastapi.responses import StreamingResponse, JSONResponse
from agent.tools.legacy.gemini_toolkit import GeminiToolkit
from agent.tools.legacy.rag_toolkit import RAGToolKit
from agent.infrastructure.runtime.pull_config_from_dynamo import download_dynamo_to_json
from agent.infrastructure.runtime.db_migrations import run_db_migrations
from agent.infrastructure.runtime.template_store import load_runtime_templates
from agent.tools.sessions_logs import build_log
from agent.memory import auto_memory
from agent.infrastructure.runtime import ratings_store
from pathlib import Path
from typing import Optional, List
import config as settings
import shutil
import uuid
import json
import traceback
import asyncio
import os
from agent.infrastructure.runtime.data_fetcher import get_user_name, get_permissions
import threading
import redis


# ==========================================================
# ⏱️ TIMEOUT GLOBAL
# ==========================================================
TIMEOUT_SECONDS = 60

TIMEOUT_MESSAGE = (
    "Desculpe, sua solicitação levou tempo demais para ser concluída. "
    "Por favor, tente reformular a frase e ajustar para uma consulta menos demorada."
)
# ==========================================================
# 🚀 Configuração do FastAPI + CORS
# ==========================================================


app = FastAPI(
    title="Agent Smart Chat API",
    description="API inteligente de orquestração de módulos Agent",
    version="1.0.0"
)

run_db_migrations()

ssl = True
if not settings.REDIS_SSL:
    ssl = False
redis_client = None
if settings.REDIS_HOST:
    redis_client = redis.Redis(
        host=settings.REDIS_HOST,
        port=settings.REDIS_PORT,
        decode_responses=True,
        ssl=ssl,
    )

ROOT_PATH = os.getenv("FASTAPI_ROOT_PATH", "").strip()

if ROOT_PATH:
    router_prefix = "/" + ROOT_PATH.lstrip("/")
else:
    router_prefix = ""

router = APIRouter(prefix=router_prefix)
origins = [
    "http://localhost:3000",
    "https://seu-site-em-producao.com",
    "*",  
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ==========================================================
# 🧠 Cache global de módulos e sessões
# ==========================================================

SESSION_TTL_SECONDS = 60 * 60 * 6

def _redis_history_key(module_name: str, session_id: str, user_id: str) -> str:
    return f"session:{user_id}:{session_id}:{module_name}:history"

def load_session_history(module_name: str, session_id: str, user_id: str):
    if not settings.USE_REDIS_CONTEXT or not redis_client:
        return None
    raw = redis_client.get(_redis_history_key(module_name, session_id, user_id))
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception:
        return None

def save_session_history(module_name: str, session_id: str, user_id: str, history):
    if not settings.USE_REDIS_CONTEXT or not redis_client:
        return
    redis_client.set(
        _redis_history_key(module_name, session_id, user_id),
        json.dumps(history, ensure_ascii=False),
        ex=SESSION_TTL_SECONDS,
    )


def parse_list(value):
    """Aceita lista, string JSON ou string separada por vírgulas."""
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            data = json.loads(value)
            if isinstance(data, list):
                return data
        except Exception:
            # caso seja "mod1,mod2,mod3"
            return [v.strip() for v in value.split(",") if v.strip()]
    return ["Demo"]


def _parse_bool(value: Optional[str]) -> bool:
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "t", "yes", "y", "on"}

# Diretório de uploads temporários
UPLOAD_DIR = Path(settings.UPLOADS_DIR)
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

# ==========================================================
# 🧩 Endpoint principal
# ==========================================================

# ==========================================================
# 🔴 STREAM CORE
# ==========================================================
async def stream_avaliar(
    request: Request,
    *,
    question: str,
    files,
    tenant_id,
    security_token,
    modules,
    session_id,
    user_id,
    message_id,
    permissions,
    auto_download_config,
    audit_enabled: bool
) -> AsyncGenerator[str, None]:

    loop = asyncio.get_running_loop()
    result_holder: dict = {} 
    cancel_event = threading.Event()

    if len(question) > 2000:
        question = "Usuário forneceu uma pergunta muito longa. Retorne a ele para reduzir o tamanho da pergunta"


    raw_question = question
    final_question = question

    async def keep_alive(task: asyncio.Future):
        while not task.done():
            yield "event: ping\ndata: keep-alive\n\n"
            await asyncio.sleep(2)

    def run_blocking(cancel_event: threading.Event):
        try:
            if cancel_event.is_set():
                return

            memory_scope = auto_memory.resolve_memory_scope(tenant_id, user_id, session_id)
            memory_llm = auto_memory.build_llm()
            memory = None
            memory_context = ""
            preferences_cleared = False
            if memory_scope and redis_client:
                memory = auto_memory.load_user_memory(redis_client, memory_scope)
                if auto_memory.should_clear_preferences(raw_question):
                    preferences_cleared = True
                    memory = auto_memory.clear_preferences(memory)
                    auto_memory.save_user_memory(redis_client, memory_scope, memory)
                rating = ratings_store.get_rate_by_message_id(message_id)
                if rating and memory_llm:
                    last_interaction = auto_memory.load_last_interaction(
                        redis_client, memory_scope
                    )
                    if last_interaction:
                        feedback_updates = auto_memory.extract_feedback_updates(
                            memory_llm,
                            question=last_interaction.get("question", ""),
                            answer=last_interaction.get("answer", ""),
                            rating=rating,
                        )
                        memory = auto_memory.apply_feedback_updates(memory, feedback_updates)
                        auto_memory.save_user_memory(redis_client, memory_scope, memory)

                memory_context = auto_memory.format_memory_for_prompt(memory)
                if memory_context:
                    nonlocal final_question
                    final_question = auto_memory.inject_memory_into_question(
                        raw_question, memory_context
                    )

            user_name = get_user_name(user_id) or "unknown"

            permissions_dict = {
                "audit": get_permissions(user_id).get("audit.read", False)
            }

            TABLE_NAME = f"agent_{tenant_id}"
            JSON_FILE = settings.AGENT_CONFIG

            if auto_download_config:
                if cancel_event.is_set():
                    return
                download_dynamo_to_json(TABLE_NAME, JSON_FILE)

            uploaded_files_img = []
            uploaded_files_not_image = []

            if files:
                for file in files:
                    if cancel_event.is_set():
                        return

                    ext = Path(file.filename).suffix
                    path = UPLOAD_DIR / f"{uuid.uuid4().hex}{ext}"
                    with open(path, "wb") as f:
                        shutil.copyfileobj(file.file, f)

                    info = {
                        "filepath": str(path),
                        "type": file.content_type,
                        "filename": file.filename,
                    }

                    if file.content_type.startswith("image/"):
                        uploaded_files_img.append(info)
                    else:
                        uploaded_files_not_image.append(info)

            allowed = parse_list(modules) + ["Audit"]

            if cancel_event.is_set():
                return

            orchestrator = MasterOrchestratorAgent(
                model="gpt-4o-mini",
                modules=allowed
            )

            templates = load_runtime_templates(tenant_id)
            chosen = orchestrator.select_module(final_question, templates, allowed)

            if cancel_event.is_set():
                return

            if chosen.lower() == "audit" and not permissions_dict["audit"]:
                result_holder["answer"] = "Sem permissão para auditoria."
                return

            loader = AgentLoader(
                module_name=chosen,
                permissions=permissions_dict,
                session_id=session_id,
                user_id=user_id,
                tenant_id=tenant_id,
                agent_template=templates,
            )
            redis_history = load_session_history(chosen, session_id, user_id)
            group_chat, manager, builder, history = loader.load()
            if redis_history:
                if isinstance(history, list) and isinstance(redis_history, list):
                    history.clear()
                    history.extend(redis_history)
                elif isinstance(history, dict) and isinstance(redis_history, dict):
                    history.clear()
                    history.update(redis_history)

            if cancel_event.is_set():
                return

            if not final_question:
                final_question = raw_question

            if uploaded_files_img:
                context_prefix = ""
                if memory_context:
                    context_prefix = (
                        "Contexto de memoria do usuario (use apenas se relevante):\n"
                        f"{memory_context}\n\n"
                    )
                final_question = f"""
    {context_prefix}
    Utilize a sua tool com os seguintes argumentos:
    question = {raw_question}
    uploaded_files = {uploaded_files_img}
    """

            if uploaded_files_not_image:
                context_prefix = ""
                if memory_context:
                    context_prefix = (
                        "Contexto de memoria do usuario (use apenas se relevante):\n"
                        f"{memory_context}\n\n"
                    )
                final_question = f"""
    {context_prefix}
    Utilize a sua tool com os seguintes argumentos:
    query = {raw_question}
    files = {uploaded_files_not_image}
    """

            if cancel_event.is_set():
                return

            # 🔴 CHAMADA PESADA DA IA
            loader.sync_agents_with_history_and_initiate(
                agents_builder=builder,
                group_manager=manager,
                history=history,
                message=final_question
            )
            save_session_history(chosen, session_id, user_id, history)

            if cancel_event.is_set():
                return  # ❌ NÃO salva resposta

            answer = group_chat.messages[-1]["content"]

            if cancel_event.is_set():
                return  # ❌ NÃO salva log

            build_log(
                session_id=session_id,
                user_id=user_id,
                customer_id=tenant_id,
                chat_id=chat_id,
                group_chat=group_chat,
                user_question=raw_question,
                log_dir=settings.LOG_DIR,
                module_name=chosen,
                is_local=settings.AUDIT_BASE_IS_LOCAL,
                user_name=user_name
            )

            if memory_scope and redis_client:
                try:
                    auto_memory.save_last_interaction(
                        redis_client,
                        memory_scope,
                        question=raw_question,
                        answer=answer,
                    )
                    profile_updates = {}
                    if memory_llm and not preferences_cleared:
                        profile_updates = auto_memory.extract_profile_updates(
                            memory_llm, raw_question
                        )
                    if profile_updates:
                        memory = memory or auto_memory.load_user_memory(
                            redis_client, memory_scope
                        )
                        memory = auto_memory.apply_profile_updates(
                            memory, profile_updates
                        )
                        auto_memory.save_user_memory(redis_client, memory_scope, memory)
                except Exception:
                    pass

            result_holder["answer"] = answer

        except Exception as e:
            if not cancel_event.is_set():
                result_holder["error"] = str(e)

    # ===== STREAM =====
    yield "event: status\ndata: Iniciando processamento...\n\n"
    task = loop.run_in_executor(None, run_blocking, cancel_event)

    try:
        await asyncio.wait_for(task, timeout=TIMEOUT_SECONDS)
    except asyncio.TimeoutError:
        cancel_event.set()  # 🔴 CANCELA PROCESSAMENTO

        yield "event: result_start\ndata: timeout\n\n"

        timeout_msg = TIMEOUT_MESSAGE
        CHUNK_SIZE = 500

        for i in range(0, len(timeout_msg), CHUNK_SIZE):
            yield (
                "event: chunk\n"
                f"data: {json.dumps(timeout_msg[i:i+CHUNK_SIZE], ensure_ascii=False)}\n\n"
            )
            yield ": flush\n\n"
            await asyncio.sleep(0)

        yield "event: end\ndata: timeout\n\n"
        return


    if "error" in result_holder:
        yield f"event: error\ndata: {result_holder['error']}\n\n"
    else:
        final_answer = result_holder["answer"]

        if not isinstance(final_answer, str):
            final_answer = json.dumps(final_answer, ensure_ascii=False)

        CHUNK_SIZE = 500

        yield "event: result_start\ndata: ok\n\n"

        for i in range(0, len(final_answer), CHUNK_SIZE):
            chunk = final_answer[i:i + CHUNK_SIZE]
            yield (
                "event: chunk\n"
                f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"
            )
            yield ": flush\n\n"
            await asyncio.sleep(0)

    yield "event: end\ndata: done\n\n"
# ==========================================================
# 🌊 ENDPOINT STREAM
# ==========================================================
@router.post("/avaliar")
async def avaliar(
    request: Request,
    question: str = Form(...),
    files: Optional[List[UploadFile]] = File(None),
    tenant_id: Optional[str] = Form("template"),
    security_token: Optional[str] = Header(None),
    modules: Optional[str] = Form(None),
    session_id: Optional[str] = Form("unknown"),
    user_id: Optional[str] = Form("unknown"),
    message_id: Optional[str] = Form(None),
    permissions: Optional[str] = Header(None),
    auto_download_config: Optional[str] = Form(None),
    audit_enabled: Optional[str] = Header(None, alias="AuditEnabled"),
):
    return StreamingResponse(
        stream_avaliar(
            request,
            question=question,
            files=files,
            tenant_id=tenant_id,
            security_token=security_token,
            modules=modules,
            session_id=session_id,
            user_id=user_id,
            message_id=message_id,
            permissions=permissions,
            auto_download_config=auto_download_config,
            audit_enabled=_parse_bool(audit_enabled),
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )

# ==========================================================
# Health
# ==========================================================
@app.get("/health")
def health():
    return {"status": "ok"}

app.include_router(router)
# ==========================================================
# Execução
# ==========================================================
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
