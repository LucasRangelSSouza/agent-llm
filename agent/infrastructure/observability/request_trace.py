from __future__ import annotations

import json
import time
import traceback
from contextvars import ContextVar
from datetime import datetime
from typing import Any, Dict, List, Optional


_CURRENT_TRACE: ContextVar["RequestTraceRecorder | None"] = ContextVar(
    "agent_request_trace",
    default=None,
)


def set_current_request_trace(trace: "RequestTraceRecorder | None"):
    return _CURRENT_TRACE.set(trace)


def reset_current_request_trace(token) -> None:
    _CURRENT_TRACE.reset(token)


def get_current_request_trace() -> "RequestTraceRecorder | None":
    return _CURRENT_TRACE.get()


def _looks_sensitive_key(key: str) -> bool:
    lowered = str(key or "").lower()
    markers = (
        "password",
        "secret",
        "token",
        "api_key",
        "apikey",
        "access_key",
        "private_key",
        "client_secret",
        "authorization",
    )
    return any(marker in lowered for marker in markers)


def _safe_jsonable(value: Any, *, redact_sensitive: bool = False) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        payload = {}
        for key, item in value.items():
            if redact_sensitive and _looks_sensitive_key(str(key)):
                payload[str(key)] = "***REDACTED***"
            else:
                payload[str(key)] = _safe_jsonable(item, redact_sensitive=redact_sensitive)
        return payload
    if isinstance(value, (list, tuple, set)):
        return [_safe_jsonable(item, redact_sensitive=redact_sensitive) for item in value]
    if hasattr(value, "dict") and callable(value.dict):
        return _safe_jsonable(value.dict(), redact_sensitive=redact_sensitive)
    if hasattr(value, "model_dump") and callable(value.model_dump):
        return _safe_jsonable(value.model_dump(), redact_sensitive=redact_sensitive)
    try:
        json.dumps(value)
        return value
    except Exception:
        return str(value)


class RequestTraceRecorder:
    def __init__(
        self,
        *,
        job_id: str,
        tenant_id: str,
        tenant_key: Optional[str],
        template_id: Optional[str],
        template_name: Optional[str],
        template_version_id: Optional[str],
        session_id: str,
        chat_id: str,
        user_id: str,
        message_id: Optional[str],
        question: str,
        modules_requested: str,
        audit_enabled: bool,
        requested_at: datetime,
    ) -> None:
        self.job_id = job_id
        self.started_at = requested_at
        self.finished_at: Optional[datetime] = None
        self.status = "created"
        self.final_answer: Optional[str] = None
        self.error: Optional[dict] = None

        self.request: Dict[str, Any] = {
            "job_id": job_id,
            "tenant_id": tenant_id,
            "tenant_key": tenant_key,
            "template_id": template_id,
            "template_name": template_name,
            "template_version_id": template_version_id,
            "session_id": session_id,
            "chat_id": chat_id,
            "user_id": user_id,
            "message_id": message_id,
            "question": question,
            "modules_requested": modules_requested,
            "audit_enabled": audit_enabled,
            "requested_at": requested_at.isoformat(),
        }
        self.runtime: Dict[str, Any] = {
            "selected_module": None,
            "template_snapshot": None,
            "ai_service": None,
            "uploaded_files": [],
            "agent_catalog": [],
            "usage_summary": None,
        }
        self.timeline: List[dict] = []
        self.agent_messages: List[dict] = []
        self.tool_calls: List[dict] = []
        self.notes: List[str] = []

    def mark_status(self, status: str, **extra: Any) -> None:
        self.status = status
        event = {
            "type": "status",
            "status": status,
            "timestamp": datetime.now().isoformat(),
        }
        if extra:
            event["extra"] = _safe_jsonable(extra, redact_sensitive=False)
        self.timeline.append(event)

    def add_note(self, text: str) -> None:
        if text:
            self.notes.append(str(text))

    def set_uploaded_files(self, files: List[dict]) -> None:
        self.runtime["uploaded_files"] = _safe_jsonable(files, redact_sensitive=False)

    def set_selected_module(self, module_name: str) -> None:
        self.runtime["selected_module"] = module_name

    def set_agent_catalog(self, catalog: List[dict]) -> None:
        self.runtime["agent_catalog"] = _safe_jsonable(catalog, redact_sensitive=False)

    def set_template_snapshot(self, template: dict) -> None:
        self.runtime["template_snapshot"] = _safe_jsonable(template, redact_sensitive=True)

    def set_ai_service(self, ai_service: dict | None) -> None:
        self.runtime["ai_service"] = _safe_jsonable(ai_service or {}, redact_sensitive=True)

    def set_usage_summary(self, usage_summary: dict | None) -> None:
        self.runtime["usage_summary"] = _safe_jsonable(usage_summary or {}, redact_sensitive=False)

    def record_agent_message(self, *, index: int, message: dict) -> None:
        payload = {
            "index": index,
            "timestamp": datetime.now().isoformat(),
            "name": message.get("name"),
            "role": message.get("role"),
            "content": _safe_jsonable(message.get("content"), redact_sensitive=False),
            "tool_calls": _safe_jsonable(message.get("tool_calls"), redact_sensitive=False),
        }
        self.agent_messages.append(payload)

    def record_tool_call(
        self,
        *,
        module_name: str,
        agent_name: str,
        toolkit_name: str,
        function_name: str,
        input_payload: Any,
        output_payload: Any = None,
        duration_ms: Optional[float] = None,
        status: str = "ok",
        error: Optional[BaseException] = None,
    ) -> None:
        payload = {
            "timestamp": datetime.now().isoformat(),
            "module_name": module_name,
            "agent_name": agent_name,
            "toolkit_name": toolkit_name,
            "function_name": function_name,
            "tool_name": f"{toolkit_name}.{function_name}",
            "status": status,
            "duration_ms": round(duration_ms or 0.0, 2),
            "input": _safe_jsonable(input_payload, redact_sensitive=False),
            "output": _safe_jsonable(output_payload, redact_sensitive=False),
        }
        if error:
            payload["error"] = {
                "type": error.__class__.__name__,
                "message": str(error),
                "stacktrace": traceback.format_exc(),
            }
        self.tool_calls.append(payload)

    def set_result(self, answer: str) -> None:
        self.final_answer = answer

    def record_error(self, error: BaseException) -> None:
        self.error = {
            "type": error.__class__.__name__,
            "message": str(error),
            "stacktrace": traceback.format_exc(),
        }

    def finalize(self) -> None:
        tzinfo = self.started_at.tzinfo
        self.finished_at = datetime.now(tzinfo) if tzinfo else datetime.now()

    def to_payload(self) -> Dict[str, Any]:
        finished_at = self.finished_at or datetime.now()
        return {
            "job_id": self.job_id,
            "status": self.status,
            "started_at": self.started_at.isoformat(),
            "finished_at": finished_at.isoformat(),
            "duration_ms": round((finished_at - self.started_at).total_seconds() * 1000, 2),
            "request": self.request,
            "runtime": self.runtime,
            "timeline": self.timeline,
            "agent_messages": self.agent_messages,
            "tool_calls": self.tool_calls,
            "final_answer": self.final_answer,
            "error": self.error,
            "notes": self.notes,
            "counts": {
                "agent_messages": len(self.agent_messages),
                "tool_calls": len(self.tool_calls),
            },
        }
