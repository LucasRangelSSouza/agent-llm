from fastapi import FastAPI, UploadFile, File, Form, APIRouter, Header
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from typing import Optional, List
import uuid
import json
import threading
import os
import redis
import config as settings
from pathlib import Path
from agent.infrastructure.runtime.db_migrations import run_db_migrations

UPLOAD_DIR = Path(settings.UPLOADS_DIR)
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
# 🔥 IMPORTA DO PROCESS_JOB
from agent.engine.process_job import (
    create_job,
    process_job,
    CHUNK_SIZE,
)

# ==========================================================
# 🚀 FastAPI
# ==========================================================
app = FastAPI(title="Agent Smart Chat API", version="1.0.0")

run_db_migrations()

ROOT_PATH = os.getenv("FASTAPI_ROOT_PATH", "").strip()
print(ROOT_PATH)


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
ssl = True
if not settings.REDIS_SSL:
    ssl = False

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
def redis_is_available() -> bool:
    try:
        redis_client = redis.Redis(
            host=settings.REDIS_HOST,
            port=settings.REDIS_PORT,
            decode_responses=True,
            ssl=ssl,
            socket_connect_timeout=2,
            socket_timeout=2,
        )
        redis_client.ping()
        return True
    except Exception:
        return False
redis_av = redis_is_available()
print(f"redis is { redis_av}")


def _parse_bool(value: Optional[str]) -> bool:
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "t", "yes", "y", "on"}


def _normalize_identifier(*candidates: Optional[str], fallback: str = "unknown") -> str:
    for candidate in candidates:
        if candidate is None:
            continue
        value = str(candidate).strip()
        if value and value.lower() != "unknown":
            return value
    return fallback

LOG_PREVIEW_LEN = 30


def _truncate_log_message(message: object, limit: int = LOG_PREVIEW_LEN) -> str:
    if message is None:
        return ""
    text = str(message)
    if len(text) <= limit:
        return text
    return text[:limit] + "..."
# ==========================================================
# 🧵 POST → CRIA JOB
# ==========================================================


@router.post("/avaliar")
async def avaliar(
    question: str = Form(...),
    files: Optional[List[UploadFile]] = File(None),
    tenant_id: str = Form("template"),
    tenant_key: Optional[str] = Form(None),
    modules: Optional[str] = Form(None),
    session_id: str = Form("unknown"),
    user_id: str = Form("unknown"),
    chat_id: str = Form("unknown"),
    template_id: Optional[str] = Form(None),
    template_name: Optional[str] = Form(None),
    template_version_id: Optional[str] = Form(None),
    message_id: Optional[str] = Form(None),
    auto_download_config: Optional[str] = Form(None),
    permissions: Optional[str] = Header(None),
):
    session_id = _normalize_identifier(session_id, chat_id, fallback="unknown")
    chat_id = _normalize_identifier(chat_id, session_id, fallback=session_id)
    user_id = _normalize_identifier(user_id, session_id, chat_id, fallback="unknown")
    audit_enabled = False
    print(f'PERMISSIONS = { permissions}')

    if permissions:
        try:
            permissions_json = json.loads(permissions)
            audit_enabled = _parse_bool(permissions_json.get("auditEnabled"))
            print(f'PERMISSIONS_JSON = { permissions_json}')
        except Exception:
            audit_enabled = False

    print(f'AUDIT_ENABLED_FINAL = {audit_enabled}')
    print(f'SESSION = { session_id}')
    print(f'CHAT ID = { chat_id}')
    if not redis_av:
        return {
            "error": "REDIS_NAO_DISPONIVEL",
            "message": "Serviço temporariamente indisponível. Tente novamente."
        }
    job_id = uuid.uuid4().hex

    create_job(job_id)

    saved_files = []
    if not files:
        print("NENHUM ARQUIVO ENVIADO!")

    if files:
        for file in files:
            ext = Path(file.filename).suffix
            path = UPLOAD_DIR / f"{uuid.uuid4().hex}{ext}"
            print (f"arquivos enviados: {path}")

            with open(path, "wb") as f:
                f.write(await file.read())  # ← leitura síncrona TOTAL

            saved_files.append({
                "filepath": str(path),
                "type": file.content_type,
                "filename": file.filename,
            })


    # 🔥 dispara thread
    thread = threading.Thread(
        target=process_job,
        kwargs=dict(
            job_id=job_id,
            question=question,
            files=saved_files,
            tenant_id=tenant_id,
            tenant_key=tenant_key,
            template_id=template_id,
            template_name=template_name,
            template_version_id=template_version_id,
            modules=modules,
            session_id=session_id,
            user_id=user_id,
            chat_id=chat_id,
            message_id=message_id,
            auto_download_config=auto_download_config,
            audit_enabled=audit_enabled,
        ),
        daemon=True
    )
    thread.start()

    return {
        "job_id": job_id,
        "status": "queued"
    }

# ==========================================================
# 🌊 GET → RESULTADO DO JOB
# ==========================================================
@router.get("/resultado/{job_id}")
async def resultado(job_id: str):
    job_key = f"job:{job_id}"

    redis_client = redis.Redis(
        host=settings.REDIS_HOST,
        port=settings.REDIS_PORT,
        decode_responses=True,
        ssl=ssl,
    )

    if not redis_client.exists(job_key):
        return {"error": "job_id não encontrado"}

    job_data = redis_client.hgetall(job_key)

    status = job_data.get("status")
    result = job_data.get("result")
    error = job_data.get("error")

    logs = "processando..."

    if settings.VERBOSE:
        logs = redis_client.lrange(f"{job_key}:logs", 0, -1)

    # ⏳ ainda processando
    if status in ("pending", "running"):
        return {
            "status": status,
            "logs": logs
        }


    # ❌ erro
    if status == "error":
        return {
            "status": "error",
            "error": error,
            "logs": logs
        }

    # ✅ finalizado → SSE CHUNKADO (IGUAL AO SEU)
    async def stream():
        yield "event: result_start\ndata: ok\n\n"

        final_answer = result or ""
        for i in range(0, len(final_answer), CHUNK_SIZE):
            chunk = final_answer[i:i + CHUNK_SIZE]
            yield (
                "event: chunk\n"
                f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"
            )

        yield "event: end\ndata: done\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream")

@router.get("/consume/{job_id}")
def consume_job(job_id: str):
    redis_client = redis.Redis(
        host=settings.REDIS_HOST,
        port=settings.REDIS_PORT,
        decode_responses=True,
        ssl=ssl,
    )

    STREAM_NAME = "job_events_stream"
    job_key = f"job:{job_id}"

    def event_generator():
        last_id = "$"

        # 🔓 OPEN
        yield f"event: open\ndata: {json.dumps({'job_id': job_id})}\n\n"

        # 📦 STATUS INICIAL
        job_data = redis_client.hgetall(job_key)
        if not job_data:
            yield "event: error\ndata: Job não encontrado\n\n"
            return

        # 🔥 ATALHO: job já finalizado
        if job_data.get("status") == "done":
            result = job_data.get("result", "")

            yield "event: result_start\ndata: ok\n\n"

            for i in range(0, len(result), CHUNK_SIZE):
                chunk = result[i:i + CHUNK_SIZE]
                yield (
                    "event: chunk\n"
                    f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"
                )

            yield "event: end\ndata: done\n\n"
            return

        # Caso contrário, segue fluxo normal
        yield f"event: status\ndata: {json.dumps(job_data)}\n\n"

        # 🪵 LOGS JÁ EXISTENTES
        #logs = redis_client.lrange(f"{job_key}:logs", 0, -1)
        #for log in logs:
        #    yield f"event: log\ndata: {json.dumps(log)}\n\n"

        # 🔁 STREAM DE EVENTOS
        while True:
            events = redis_client.xread(
                {STREAM_NAME: last_id},
                block=5000,
                count=10
            )

            if not events:
                yield "event: ping\ndata: {}\n\n"
                continue

            for _, messages in events:
                for event_id, data in messages:
                    last_id = event_id

                    if data.get("job_id") != job_id:
                        continue

                    event_type = data.get("event", "message")

                    # 🪵 LOG / STATUS
                    if event_type == "log":
                        preview = _truncate_log_message(data.get("message"))
                        yield (
                            "event: log\n"
                            f"data: {json.dumps(preview, ensure_ascii=False)}\n\n"
                        )
                        continue

                    # ❌ ERROR
                    if event_type == "error":
                        job_data = redis_client.hgetall(job_key)
                        yield (
                            "event: error\n"
                            f"data: {json.dumps(job_data.get('error'))}\n\n"
                        )
                        yield "event: end\ndata: error\n\n"
                        return

                    # ✅ DONE → STREAM RESULT
                    if event_type == "done":
                        job_data = redis_client.hgetall(job_key)
                        result = job_data.get("result", "")

                        yield "event: result_start\ndata: ok\n\n"

                        for i in range(0, len(result), CHUNK_SIZE):
                            chunk = result[i:i + CHUNK_SIZE]
                            yield (
                                "event: chunk\n"
                                f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"
                            )

                        yield "event: end\ndata: done\n\n"
                        return

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )

# ==========================================================
# ❤️ HEALTH
# ==========================================================
@app.get("/health")
def health():
    return {"status": "ok"}
@router.get("/health")
def health():
    return {"status": "ok"}

app.include_router(router)

# ==========================================================
# ▶️ RUN
# ==========================================================
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
