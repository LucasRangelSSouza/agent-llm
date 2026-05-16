import json
import logging
import re
from pathlib import Path
from typing import Any

import boto3
from botocore.client import Config

import config as settings

logger = logging.getLogger(__name__)


def _sanitize_component(value: str, fallback: str) -> str:
    text = (value or fallback or "").strip()
    text = re.sub(r"[^0-9A-Za-z_-]+", "_", text)
    return text or fallback


def _build_output_path(job_id: str, user_name: str, finished_at: str) -> Path:
    base_dir = Path(settings.RUNTIME_LOGS_DIR)
    base_dir.mkdir(parents=True, exist_ok=True)
    safe_user = _sanitize_component(user_name, "unknown")
    safe_time = _sanitize_component(finished_at, "ts")
    return base_dir / f"{job_id}_{safe_user}_{safe_time}.json"


def _extract_request_metadata(payload: Any) -> dict:
    if isinstance(payload, dict):
        request = payload.get("request") or {}
        runtime = payload.get("runtime") or {}
        return {
            "tenant_key": request.get("tenant_key") or request.get("tenant_id") or "",
            "template_name": request.get("template_name") or "",
            "module_name": runtime.get("selected_module") or "",
            "chat_id": request.get("chat_id") or "",
        }
    return {"tenant_key": "", "template_name": "", "module_name": "", "chat_id": ""}


def _build_object_key(job_id: str, payload: Any, *, user_name: str, finished_at: str) -> str:
    metadata = _extract_request_metadata(payload)
    safe_tenant = _sanitize_component(metadata.get("tenant_key") or "", "unknown_tenant")
    safe_template = _sanitize_component(metadata.get("template_name") or "", "unknown_template")
    safe_module = _sanitize_component(metadata.get("module_name") or "", "unknown_module")
    safe_chat = _sanitize_component(metadata.get("chat_id") or "", "unknown_chat")
    safe_time = _sanitize_component(finished_at, "ts")
    prefix = (getattr(settings, "AI_REQUEST_TRACE_PREFIX", "") or "observability/ai-runtime").strip("/")
    return (
        f"{prefix}/{safe_tenant}/"
        f"{safe_template}_{safe_module}_{safe_chat}_{safe_time}_{job_id}.json"
    )


def _upload_to_s3(job_id: str, payload: Any, payload_text: str, *, user_name: str, finished_at: str) -> dict | None:
    if not settings.FILE_STORAGE_ENDPOINT or not settings.FILE_STORAGE_BUCKET:
        return None

    object_key = _build_object_key(job_id, payload, user_name=user_name, finished_at=finished_at)

    client = boto3.client(
        "s3",
        endpoint_url=settings.FILE_STORAGE_ENDPOINT,
        aws_access_key_id=settings.FILE_STORAGE_ACCESS_KEY,
        aws_secret_access_key=settings.FILE_STORAGE_SECRET_KEY,
        region_name=settings.FILE_STORAGE_REGION,
        config=Config(signature_version="s3v4"),
    )
    client.put_object(
        Bucket=settings.FILE_STORAGE_BUCKET,
        Key=object_key,
        Body=payload_text.encode("utf-8"),
        ContentType="application/json; charset=utf-8",
    )

    public_base = (settings.FILE_STORAGE_PUBLIC_ENDPOINT or settings.FILE_STORAGE_ENDPOINT or "").rstrip("/")
    if public_base and settings.FILE_STORAGE_URL_MODE == "permanent":
        url = f"{public_base}/{settings.FILE_STORAGE_BUCKET}/{object_key}"
    else:
        url = client.generate_presigned_url(
            "get_object",
            Params={"Bucket": settings.FILE_STORAGE_BUCKET, "Key": object_key},
            ExpiresIn=settings.FILE_STORAGE_SIGNED_URL_EXPIRES_SECONDS,
        )
    return {"bucket": settings.FILE_STORAGE_BUCKET, "object_key": object_key, "url": url}


def upload_runtime_log(job_id: str, payload: Any, *, user_name: str, finished_at: str) -> dict:
    output_path = _build_output_path(job_id, user_name, finished_at)
    payload_text = json.dumps(payload, ensure_ascii=False, indent=2)
    response = {"saved_local": False, "saved_remote": False, "local_path": str(output_path), "remote": None}
    try:
        output_path.write_text(payload_text, encoding="utf-8")
        response["saved_local"] = True
    except Exception as exc:
        logger.error("Erro ao salvar log runtime localmente: %s", exc)
    try:
        remote = _upload_to_s3(job_id, payload, payload_text, user_name=user_name, finished_at=finished_at)
        if remote:
            response["saved_remote"] = True
            response["remote"] = remote
    except Exception as exc:
        logger.error("Erro ao enviar log runtime para storage S3/MinIO: %s", exc)
    return response
