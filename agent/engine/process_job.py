from fastapi import FastAPI, Request, UploadFile, File, Form, Header, APIRouter
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware

import psutil
from threading import Semaphore, Timer

from agent.engine.agent_loader import AgentLoader
from agent.modules.agents.master_orchestrator_agent import MasterOrchestratorAgent
from agent.infrastructure.runtime.pull_config_from_dynamo import download_dynamo_to_json
from agent.tools.sessions_logs import build_log
from agent.infrastructure.runtime.data_fetcher import get_user_name, get_permissions
from agent.infrastructure.runtime.metadata_utils import embed_prompt_metadata
from agent.modules.db.front_db import FrontDB
from agent.infrastructure.runtime.runtime_logs import upload_runtime_log
from agent.infrastructure.runtime.ai_service import resolve_ai_service
from agent.infrastructure.runtime.template_store import load_runtime_templates
from agent.modules.db.audit_db import AuditDB
from agent.infrastructure.observability.request_trace import (
    RequestTraceRecorder,
    reset_current_request_trace,
    set_current_request_trace,
)

from pathlib import Path
from typing import Optional, List, AsyncGenerator
import config as settings

import redis
import shutil
import uuid
import json
import asyncio
import os
import threading
import time
from queue import Queue, Empty
from threading import Lock
from datetime import datetime
from zoneinfo import ZoneInfo
from autogen import gather_usage_summary
from opentelemetry import trace as otel_trace
from opentelemetry.trace import SpanKind

from agent.infrastructure.observability.telemetry import get_tracer, setup_tracing

# =========================
from agent.infrastructure.runtime import ratings_store

import dotenv

from agent.infrastructure.observability.setup_logger import LOGGER, LoggerManager
from agent.infrastructure.observability.trace import set_trace_id

# =========================
dotenv.load_dotenv()

project_id = os.getenv("LANGSMITH_PROJECT_ID")
if project_id:
    os.environ.setdefault("LANGSMITH_PROJECT", project_id)

setup_tracing()

# =========================
# Redis Client
# =========================

ssl = True
if not settings.REDIS_SSL:
    ssl = False
redis_client = redis.Redis(
    host=settings.REDIS_HOST,
    port=settings.REDIS_PORT,
    decode_responses=True,
    ssl=ssl,
)

# =========================
# Constantes / Cache
# =========================
CHUNK_SIZE = 500

UPLOAD_DIR = Path(settings.UPLOADS_DIR)
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

MAX_CONCURRENT_JOBS = 4
MAX_MEMORY_PERCENT = 80
JOB_TIMEOUT_SECONDS = 10000
job_semaphore = threading.Semaphore(MAX_CONCURRENT_JOBS)

# =========================
# Redis Session Context
# =========================
SESSION_TTL_SECONDS = 60 * 60 * 6  # 6h

USE_REDIS_CONTEXT = settings.USE_REDIS_CONTEXT



def _trim_history(history):
    max_messages = max(0, int(getattr(settings, "REDIS_HISTORY_MAX_MESSAGES_PER_AGENT", 8)))
    if not max_messages:
        return history
    if isinstance(history, dict):
        return {
            agent_name: messages[-max_messages:] if isinstance(messages, list) else messages
            for agent_name, messages in history.items()
        }
    if isinstance(history, list):
        return history[-max_messages:]
    return history


def load_session_history(module_name: str, session_id: str, user_id: str, chat_id: str | None = None):
    if not USE_REDIS_CONTEXT:
        return None
    return load_history_from_redis(module_name, session_id, user_id, chat_id)


def save_session_history(module_name: str, session_id: str, user_id: str, history, chat_id: str | None = None):
    if not USE_REDIS_CONTEXT:
        return
    save_history_to_redis(module_name, session_id, user_id, history, chat_id)

def redis_history_key(module_name: str, session_id: str, user_id: str, chat_id: str | None = None) -> str:
    history_scope = (chat_id or "").strip() or session_id
    return f"chat:{user_id}:{history_scope}:{module_name}:history"


def load_history_from_redis(module_name: str, session_id: str, user_id: str, chat_id: str | None = None):
    key = redis_history_key(module_name, session_id, user_id, chat_id)
    raw = redis_client.get(key)
    if not raw:
        return None
    try:
        return _trim_history(json.loads(raw))
    except Exception:
        return None


def save_history_to_redis(module_name: str, session_id: str, user_id: str, history, chat_id: str | None = None):
    key = redis_history_key(module_name, session_id, user_id, chat_id)
    redis_client.set(
        key,
        json.dumps(_trim_history(history), ensure_ascii=False),
        ex=SESSION_TTL_SECONDS
    )


def build_recent_chat_context(tenant_id: str, chat_id: str | None) -> str | None:
    if not chat_id:
        return None

    try:
        db = AuditDB(tenant_id=tenant_id, is_local=settings.AUDIT_BASE_IS_LOCAL)
        rows = db.fetch_recent_chat_interactions(
            chat_id,
            limit=getattr(settings, "CHAT_CONTEXT_MAX_INTERACTIONS", 6),
        )
    except Exception:
        return None

    if not rows:
        return None

    lines = [
        "[CONTEXTO DO CHAT ATUAL]",
        "Use apenas como memoria recente desta conversa. Nao misture com outros chats.",
    ]
    for index, row in enumerate(rows, start=1):
        question = (row.get("user_question") if hasattr(row, "get") else row[0]) or ""
        answer = (row.get("content") if hasattr(row, "get") else row[1]) or ""
        question = str(question).strip()
        answer = str(answer).strip()
        if not question and not answer:
            continue
        lines.append(f"{index}. Usuario: {question}")
        if answer:
            lines.append(f"   Assistente: {answer}")

    return "\n".join(lines) if len(lines) > 2 else None


def export_runtime_env_from_template(agent_template: dict, modules: str) -> None:
    if not isinstance(agent_template, dict):
        return

    module_candidates = [part.strip() for part in (modules or "").split(",") if part.strip()]
    module_candidates.extend([name for name in agent_template.keys() if name not in module_candidates])

    for module_name in module_candidates:
        module_payload = agent_template.get(module_name)
        if not isinstance(module_payload, dict):
            continue
        athena = dict(module_payload.get("athena_connection") or {})
        if not athena:
            continue

        aws_access_key_id = athena.get("aws_access_key_id") or ""
        aws_secret_access_key = athena.get("aws_secret_access_key") or ""
        if not aws_access_key_id or not aws_secret_access_key:
            continue

        os.environ["AWS_ACCESS_KEY_ID"] = aws_access_key_id
        os.environ["AWS_SECRET_ACCESS_KEY"] = aws_secret_access_key

        aws_session_token = athena.get("aws_session_token") or ""
        if aws_session_token:
            os.environ["AWS_SESSION_TOKEN"] = aws_session_token
        else:
            os.environ.pop("AWS_SESSION_TOKEN", None)

        region_name = athena.get("region_name") or "us-east-1"
        os.environ["AWS_DEFAULT_REGION"] = region_name
        os.environ["AWS_REGION"] = region_name

        output_location = athena.get("output_location") or ""
        if output_location:
            os.environ["ATHENA_OUTPUT_LOCATION"] = output_location
            if not os.getenv("GRAPHS_S3_BASE"):
                os.environ["GRAPHS_S3_BASE"] = output_location
            if not os.getenv("EXCEL_S3_BASE"):
                os.environ["EXCEL_S3_BASE"] = output_location
        return


def build_template_trace_snapshot(agent_template: dict, module_name: str) -> dict:
    snapshot = {}
    module_payload = agent_template.get(module_name)
    if isinstance(module_payload, dict):
        snapshot[module_name] = module_payload
    audit_payload = agent_template.get("Audit")
    if module_name != "Audit" and isinstance(audit_payload, dict):
        snapshot["Audit"] = audit_payload
    if not snapshot and isinstance(agent_template, dict):
        snapshot = agent_template
    return snapshot


def build_agent_catalog(agent_template: dict, module_name: str) -> list[dict]:
    module_payload = agent_template.get(module_name) or {}
    submodules = module_payload.get("submodules") or {}
    catalog = []
    for agent_name, data in submodules.items():
        if not isinstance(data, dict):
            continue
        catalog.append(
            {
                "name": agent_name,
                "type": data.get("type"),
                "tools": list(data.get("tools") or []),
                "allowed_interactions": list(data.get("allowed_interactions") or []),
                "rag_files": list(data.get("rag_files") or []),
            }
        )
    return catalog


# =========================
# Redis Job Helpers
# =========================
def create_job(job_id: str):
    redis_client.hset(
        f"job:{job_id}",
        mapping={
            "status": "pending",
            "created_at": time.time(),
            "updated_at": time.time(),
        }
    )
    redis_client.delete(f"job:{job_id}:logs")
    


def set_job_status(job_id: str, status: str, **extra):
    payload = {
        "status": status,
        "updated_at": time.time(),
    }
    payload.update(extra)
    redis_client.hset(f"job:{job_id}", mapping=payload)


def append_job_log(job_id: str, text: str):
    redis_client.rpush(f"job:{job_id}:logs", text)


# =========================
# Tool extraction
# =========================
def extract_tool_info(msg, all_messages):
    """
    Retorna (tool_name, tool_args, tool_result) ou None
    """
    if "tool_calls" not in msg:
        return None

    try:
        tc = msg["tool_calls"][0]
        tool_name = tc["function"].get("name")
        tool_args = tc["function"].get("arguments")

        for m in reversed(all_messages):
            if m.get("role") == "tool" and m.get("content"):
                return tool_name, tool_args, m["content"]

        return tool_name, tool_args, None

    except Exception:
        return None


def _should_hide_history_payload_text(text: str) -> bool:
    if settings.SHOW_HISTORY_QUERY_PAYLOADS:
        return False
    if not text:
        return False
    is_history_payload = (
        "[METADATA]" in text
        or "Resultado encontrado:" in text
        or "| Usuário | User ID |" in text
        or "| User ID |" in text
    )
    return is_history_payload and len(text) > 400


# =========================
# Job Processor
# =========================
def _process_job_impl(
    job_id: str,
    *,
    question: str,
    files,
    tenant_id: str,
    tenant_key: Optional[str] = None,
    template_id: Optional[str] = None,
    template_name: Optional[str] = None,
    template_version_id: Optional[str] = None,
    modules: str,
    session_id: str,
    chat_id: str,
    user_id: str,
    message_id: Optional[str] = None,
    auto_download_config: bool,
    audit_enabled: bool,
    logger: LoggerManager = LOGGER
):
    request_started_at = datetime.now(ZoneInfo("America/Sao_Paulo"))
    trace_recorder = RequestTraceRecorder(
        job_id=job_id,
        tenant_id=tenant_id,
        tenant_key=tenant_key,
        template_id=template_id,
        template_name=template_name,
        template_version_id=template_version_id,
        session_id=session_id,
        chat_id=chat_id,
        user_id=user_id,
        message_id=message_id,
        question=question,
        modules_requested=modules,
        audit_enabled=audit_enabled,
        requested_at=request_started_at,
    )
    trace_token = set_current_request_trace(trace_recorder)
    trace_recorder.mark_status("starting")

    set_trace_id(f"{session_id}-{user_id}")
    logger.log_info(f"Starting job to process question {question}")

    user_name = "unknown"
    usage_summary = None
    acquired = False
    cancel_event = threading.Event()
    timeout_timer = None

    try:
        raw_question = question
        normalized_question = raw_question
        try:
            front_db = FrontDB(
                use_local=settings.USE_LOCAL_FRONT_DB,
                read_only=not settings.USE_LOCAL_FRONT_DB,
            )
            feedback_context = (
                front_db.build_feedback_context(chat_id or session_id)
                if False
                else None
            )
            if feedback_context:
                normalized_question = (
                    f"{feedback_context}\n\n"
                    "INSTRUCOES IMPORTANTES: use o bloco acima apenas internamente. "
                    "NUNCA responda com resumo de feedbacks e NAO use as palavras "
                    "'Manter', 'Melhorar', 'Evitar' ou 'Resumo de Feedbacks' na resposta final. "
                    "Responda SOMENTE a pergunta do usuario.\n\n"
                    f"Pergunta do usuario: {normalized_question}"
                )
        except Exception as error:
            trace_recorder.add_note(f"Falha ao carregar feedback context: {error}")

        chat_context = build_recent_chat_context(tenant_id, chat_id)
        if chat_context:
            normalized_question = (
                f"{chat_context}\n\n"
                "[PERGUNTA ATUAL]\n"
                f"{normalized_question}"
            )

        question_time = datetime.now(ZoneInfo("America/Sao_Paulo"))
        hoje_str = question_time.strftime(
            "hoje é %d de %B de %Y às %H:%M:%S horário de Brasília. "
            "Use essa informação para responder perguntas relacionadas a datas e horários."
        )

        runtime_template_key = (tenant_key or tenant_id or "").strip()
        templates = load_runtime_templates(runtime_template_key)
        export_runtime_env_from_template(templates, modules)
        trace_recorder.mark_status("template_loaded", runtime_template_key=runtime_template_key)

        question = json.dumps(
            {"data": hoje_str, "question": normalized_question},
            ensure_ascii=False,
        )

        acquired = job_semaphore.acquire()
        final_question = question
        if not acquired:
            raise RuntimeError("Servidor ocupado (limite de jobs atingido)")

        mem = psutil.virtual_memory()
        if mem.percent >= MAX_MEMORY_PERCENT:
            raise RuntimeError("Servidor sem memória disponível")

        set_job_status(job_id, "running")
        trace_recorder.mark_status("running")

        def emit_log(text: str):
            append_job_log(job_id, text)
            trace_recorder.add_note(text)
            redis_client.xadd(
                "job_events_stream",
                {
                    "job_id": job_id,
                    "event": "log",
                    "message": text,
                    "timestamp": str(time.time()),
                },
            )

        def monitor_group_chat(group_chat, start_index):
            last_len = start_index
            while not cancel_event.is_set():
                msgs = group_chat.messages
                if len(msgs) > last_len:
                    for offset, msg in enumerate(msgs[last_len:], start=last_len):
                        trace_recorder.record_agent_message(index=offset, message=msg)
                        lines = [f"Agente acionado: {msg.get('name', 'desconhecido')}"]

                        if settings.SHOW_AGENT_INTERACTION_LOGS:
                            tool_info = extract_tool_info(msg, msgs)
                            if tool_info:
                                tool_name, tool_args, tool_result = tool_info
                                lines.append(f"Agente acionou a ferramenta: {tool_name}")
                                if tool_args:
                                    tool_args_text = str(tool_args)
                                    if _should_hide_history_payload_text(tool_args_text):
                                        lines.extend(["Argumentos da ferramenta:", "[payload longo de histórico oculto]"])
                                    else:
                                        lines.extend(["Argumentos da ferramenta:", tool_args_text])
                                if tool_result:
                                    tool_result_text = str(tool_result)
                                    if _should_hide_history_payload_text(tool_result_text):
                                        lines.extend(["Resposta da ferramenta:", "[payload longo de histórico oculto]"])
                                    else:
                                        lines.extend(["Resposta da ferramenta:", tool_result_text])

                            content = msg.get("content")
                            if content not in (None, "", "None"):
                                content_text = str(content)
                                if _should_hide_history_payload_text(content_text):
                                    lines.extend(["Resposta gerada pelo agente:", "[payload longo de histórico oculto]"])
                                else:
                                    lines.extend(["Resposta gerada pelo agente:", content_text])

                        for line in lines:
                            emit_log(line)
                    last_len = len(msgs)
                time.sleep(1)

        def timeout_handler():
            cancel_event.set()
            trace_recorder.mark_status("timeout")
            emit_log("⛔ Job cancelado por timeout")

        timeout_timer = Timer(JOB_TIMEOUT_SECONDS, timeout_handler)
        timeout_timer.start()

        emit_log("🚀 Iniciando processamento")
        uploaded_files_img = []
        uploaded_files_not_image = []
        original_question = question

        for file in files or []:
            info = {
                "filepath": file["filepath"],
                "type": file["type"],
                "filename": file["filename"],
            }
            if file["type"] and file["type"].startswith("image/"):
                uploaded_files_img.append(info)
            else:
                uploaded_files_not_image.append(info)
                final_question = original_question

        trace_recorder.set_uploaded_files(uploaded_files_img + uploaded_files_not_image)

        if uploaded_files_img or uploaded_files_not_image:
            payload = {
                "question": original_question,
                "uploaded_images": uploaded_files_img,
                "uploaded_files": uploaded_files_not_image,
            }
            final_question = f"""
        Você recebeu uma solicitação do usuário com arquivos anexados.

        Use as tools apropriadas quando necessário.

        Payload:
        {json.dumps(payload, ensure_ascii=False, indent=2)}
        """

        permissions = {"audit": get_permissions(user_id).get("audit.read", False)}

        if auto_download_config:
            download_dynamo_to_json(f"agent_{tenant_id}", settings.AGENT_CONFIG)

        if audit_enabled:
            chosen = "Audit"
        else:
            allowed = [m for m in (modules.split(",") if modules else []) if m.lower() != "audit"]
            orchestrator = MasterOrchestratorAgent(
                modules=allowed,
                agent_template=templates,
            )
            templates_for_routing = templates
            if not allowed:
                templates_for_routing = {
                    key: value for key, value in templates.items() if key.lower() != "audit"
                }
            chosen = orchestrator.select_module(question, templates_for_routing, allowed)

        trace_recorder.set_selected_module(chosen)
        trace_recorder.set_template_snapshot(build_template_trace_snapshot(templates, chosen))
        trace_recorder.set_ai_service(resolve_ai_service(templates, chosen))
        trace_recorder.set_agent_catalog(build_agent_catalog(templates, chosen))
        trace_recorder.mark_status("module_selected", module_name=chosen)

        loader = AgentLoader(
            module_name=chosen,
            permissions=permissions,
            session_id=session_id,
            user_id=user_id,
            tenant_id=tenant_id,
            agent_template=templates,
        )

        redis_history = load_session_history(chosen, session_id, user_id, chat_id=chat_id)
        group_chat, manager, builder, history = loader.load()

        if redis_history:
            if isinstance(history, list) and isinstance(redis_history, list):
                history.clear()
                history.extend(redis_history)
            elif isinstance(history, dict) and isinstance(redis_history, dict):
                history.clear()
                history.update(redis_history)
            else:
                emit_log("Historico do Redis incompatível, ignorando restore")

        start_index = len(group_chat.messages)
        monitor_thread = threading.Thread(
            target=monitor_group_chat,
            args=(group_chat, start_index),
            daemon=True,
        )
        monitor_thread.start()

        user_name = get_user_name(user_id) or "unknown"
        wrapped_question = embed_prompt_metadata(final_question, job_id, user_id, user_name)

        loader.sync_agents_with_history_and_initiate(
            agents_builder=builder,
            group_manager=manager,
            history=history,
            message=wrapped_question,
        )

        save_session_history(chosen, session_id, user_id, history, chat_id=chat_id)
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
            user_name=user_name,
        )

        if settings.USE_LOCAL_FRONT_DB:
            try:
                answer_time = datetime.now(ZoneInfo("America/Sao_Paulo"))
                rows = [
                    (session_id, raw_question, "user", question_time.isoformat(), None),
                    (
                        session_id,
                        group_chat.messages[-1]["content"],
                        "assistant",
                        answer_time.isoformat(),
                        None,
                    ),
                ]
                FrontDB(use_local=True).insert_messages(rows)
            except Exception as error:
                trace_recorder.add_note(f"Falha ao gravar mensagens no front DB local: {error}")

        cancel_event.set()
        time.sleep(0.3)

        final_answer = group_chat.messages[-1]["content"]
        trace_recorder.set_result(final_answer)
        set_job_status(job_id, "done", result=final_answer)

        if builder:
            module_agents = [
                agent
                for agent in builder.active_agents.get(chosen, {}).values()
                if agent is not None
            ]
            if module_agents:
                try:
                    usage_summary = gather_usage_summary(module_agents)
                except Exception as error:
                    emit_log(f"⚠️ Não foi possível coletar uso de tokens: {error}")

        if usage_summary:
            trace_recorder.set_usage_summary(usage_summary)
            if settings.SHOW_USAGE_LOGS:
                logger.log_info(
                    f"usage_including_cached_inference: {usage_summary['usage_including_cached_inference']}"
                )
                logger.log_info(
                    f"usage_excluding_cached_inference: {usage_summary['usage_excluding_cached_inference']}"
                )
                emit_log(f"Custos de tokens registrados: {json.dumps(usage_summary, ensure_ascii=False)}")

            current_span = otel_trace.get_current_span()
            if current_span:
                inc = usage_summary.get("usage_including_cached_inference", {})
                exc = usage_summary.get("usage_excluding_cached_inference", {})
                if inc:
                    if (total_cost := inc.get("total_cost")) is not None:
                        current_span.set_attribute("agent.usage.including_cached.total_cost", float(total_cost))
                    if (total_tokens := inc.get("total_tokens")) is not None:
                        current_span.set_attribute("agent.usage.including_cached.total_tokens", int(total_tokens))
                if exc:
                    if (total_cost := exc.get("total_cost")) is not None:
                        current_span.set_attribute("agent.usage.excluding_cached.total_cost", float(total_cost))
                    if (total_tokens := exc.get("total_tokens")) is not None:
                        current_span.set_attribute("agent.usage.excluding_cached.total_tokens", int(total_tokens))

        trace_recorder.mark_status("completed")
        redis_client.xadd(
            "job_events_stream",
            {
                "job_id": job_id,
                "event": "done",
                "timestamp": time.time(),
            },
        )

    except Exception as error:
        trace_recorder.record_error(error)
        trace_recorder.mark_status("error")
        set_job_status(job_id, "error", error=str(error))
        redis_client.xadd(
            "job_events_stream",
            {
                "job_id": job_id,
                "event": "error",
                "timestamp": time.time(),
            },
        )

    finally:
        cancel_event.set()
        if timeout_timer:
            timeout_timer.cancel()
        if acquired:
            job_semaphore.release()

        trace_recorder.finalize()
        try:
            upload_result = upload_runtime_log(
                job_id,
                trace_recorder.to_payload(),
                user_name=user_name,
                finished_at=(trace_recorder.finished_at or request_started_at).isoformat(),
            )
            if upload_result.get("saved_remote"):
                append_job_log(job_id, f"Trace estruturado salvo em {upload_result['remote']['object_key']}")
        except Exception as upload_error:
            append_job_log(job_id, f"Falha ao salvar trace estruturado: {upload_error}")
        reset_current_request_trace(trace_token)


def process_job(
    job_id: str,
    *,
    question: str,
    files,
    tenant_id: str,
    tenant_key: Optional[str] = None,
    template_id: Optional[str] = None,
    template_name: Optional[str] = None,
    template_version_id: Optional[str] = None,
    modules: str,
    session_id: str,
    chat_id: str,
    user_id: str,
    message_id: Optional[str] = None,
    auto_download_config: bool,
    audit_enabled: bool
):
    job_requested_at = datetime.now(ZoneInfo("America/Sao_Paulo"))
    tracer = get_tracer("agent.process_job")
    span_name = f"agent_process_job_{job_id}_{user_id}"
    attributes = {
        "agent.job_id": job_id,
        "agent.tenant_id": tenant_id,
        "agent.tenant_key": tenant_key,
        "agent.template_id": template_id,
        "agent.template_name": template_name,
        "agent.template_version_id": template_version_id,
        "agent.session_id": session_id,
        "agent.chat_id": chat_id,
        "agent.user_id": user_id,
        "agent.modules_requested": modules,
        "agent.audit_enabled": audit_enabled,
        "agent.file_count": len(files) if files else 0,
        "agent.job_requested_at": job_requested_at.isoformat(),
    }
    attributes = {k: v for k, v in attributes.items() if v not in (None, "")}

    with tracer.start_as_current_span(
        span_name,
        kind=SpanKind.SERVER,
        attributes=attributes,
    ):
        return _process_job_impl(
            job_id=job_id,
            question=question,
            files=files,
            tenant_id=tenant_id,
            tenant_key=tenant_key,
            template_id=template_id,
            template_name=template_name,
            template_version_id=template_version_id,
            modules=modules,
            session_id=session_id,
            chat_id=chat_id,
            user_id=user_id,
            message_id=message_id,
            auto_download_config=auto_download_config,
            audit_enabled=audit_enabled,
        )
