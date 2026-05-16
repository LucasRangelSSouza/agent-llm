import logging
from typing import Dict, Optional

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

_EXPORTER_PROTOCOL = "grpc"
_EXPORTER_FALLBACK_ERROR: Optional[Exception] = None
try:
    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter  # type: ignore[attr-defined]
except Exception as exc:  # pragma: no cover - fallback for old SDKs
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter  # type: ignore[attr-defined]

    _EXPORTER_PROTOCOL = "http"
    _EXPORTER_FALLBACK_ERROR = exc

from openinference.instrumentation.autogen import AutogenInstrumentor
from openinference.instrumentation.openai import OpenAIInstrumentor

import config as settings

try:
    from langsmith.integrations.otel import configure as langsmith_configure  # type: ignore[attr-defined]
except ImportError:  # pragma: no cover - optional dependency
    langsmith_configure = None

_LOGGER = logging.getLogger(__name__)
_tracing_configured = False
_AUTO_INSTRUMENTOR = AutogenInstrumentor()
_OPENAI_INSTRUMENTOR = OpenAIInstrumentor()


def _parse_otlp_headers(raw: Optional[str]) -> Optional[Dict[str, str]]:
    if not raw:
        return None
    cleaned = [entry.strip() for entry in raw.split(",") if entry.strip()]
    headers: Dict[str, str] = {}
    for entry in cleaned:
        if "=" not in entry:
            continue
        key, value = entry.split("=", 1)
        headers[key.strip()] = value.strip()
    return headers or None


def _resolve_endpoint(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    endpoint = raw.rstrip("/")
    if _EXPORTER_PROTOCOL == "http":
        if not endpoint.endswith("/v1/traces"):
            endpoint = f"{endpoint}/v1/traces"
    return endpoint


def _instrument_libraries() -> None:
    try:
        _AUTO_INSTRUMENTOR.instrument()
        _OPENAI_INSTRUMENTOR.instrument()
        _LOGGER.info("AutoGen/OpenAI instrumentors attached.")
    except Exception as error:  # pragma: no cover - best effort only
        _LOGGER.warning("Failed to instrument AutoGen/OpenAI: %s", error)



def _configure_langsmith() -> None:
    if not langsmith_configure or not settings.LANGSMITH_API_KEY:
        return
    try:
        langsmith_configure(
            project_name=settings.LANGSMITH_PROJECT_ID,
            api_key=settings.LANGSMITH_API_KEY,
            endpoint=settings.LANGSMITH_ENDPOINT,
            workspace_id=settings.LANGSMITH_WORKSPACE_ID,
        )
        _LOGGER.info("LangSmith OTEL integration configured for project %s", settings.LANGSMITH_PROJECT_ID)
    except Exception as error:  # pragma: no cover
        _LOGGER.warning("LangSmith OTEL configuration failed: %s", error)


def setup_tracing() -> None:
    global _tracing_configured
    if _tracing_configured:
        return

    if not settings.LANGSMITH_TRACING:
        _LOGGER.debug("LangSmith tracing disabled via LANGSMITH_TRACING.")
        return

    instrumentation_disabled = settings.AUTOGEN_DISABLE_RUNTIME_TRACING

    endpoint = _resolve_endpoint(settings.OTEL_EXPORTER_OTLP_ENDPOINT)
    if _EXPORTER_PROTOCOL == "http" and _EXPORTER_FALLBACK_ERROR:
        _LOGGER.warning(
            "gRPC OTLP exporter could not be imported (%s); using HTTP exporter instead.",
            _EXPORTER_FALLBACK_ERROR,
        )
    if not endpoint:
        _LOGGER.warning(
            "Tracing is enabled but OTLP endpoint is not configured (OTEL_EXPORTER_OTLP_ENDPOINT). "
            "Skipping tracer setup."
        )
        return

    manifest = Resource.create({"service.name": settings.OTEL_SERVICE_NAME})
    exporter_kwargs = {"endpoint": endpoint}
    headers = _parse_otlp_headers(settings.OTEL_EXPORTER_OTLP_HEADERS)
    if headers:
        exporter_kwargs["headers"] = headers
    if _EXPORTER_PROTOCOL == "grpc":
        exporter_kwargs["insecure"] = settings.OTEL_EXPORTER_OTLP_INSECURE

    exporter = OTLPSpanExporter(**exporter_kwargs)
    provider = TracerProvider(resource=manifest)
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    if instrumentation_disabled:
        _LOGGER.info("AutoGen runtime tracing disabled via AUTOGEN_DISABLE_RUNTIME_TRACING.")
    else:
        _instrument_libraries()
    _configure_langsmith()
    _tracing_configured = True
    _LOGGER.info(
        "Tracing configured for service %s → %s [%s]",
        settings.OTEL_SERVICE_NAME,
        endpoint,
        _EXPORTER_PROTOCOL,
    )


def is_tracing_configured() -> bool:
    return _tracing_configured


def get_tracer(name: str):
    return trace.get_tracer(name)
