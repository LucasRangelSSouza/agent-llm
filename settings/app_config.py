import os
from dotenv import load_dotenv
import redis
import logging

# Carrega variÃ¡veis do arquivo .env
load_dotenv()

def get_config(tenant_id: str):
    return f"agent_{tenant_id}.json"

# Ambiente
APP_ENVIRONMENT = os.getenv("APP_ENVIRONMENT")

def _parse_bool(value) -> bool:
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "t", "yes", "y", "on"}

# Verbose / Logging
VERBOSE = False #_parse_bool(os.getenv("VERBOSE", "true"))
if not VERBOSE:
    logging.getLogger().setLevel(logging.WARNING)
    try:
        import builtins as _builtins
        def _quiet_print(*args, **kwargs):
            return None
        _builtins.print = _quiet_print
    except Exception:
        pass

# Modelos e APIs
MODEL_OPENAI = os.getenv("MODEL_OPENAI")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

MODEL_GOOGLE = os.getenv("MODEL_GOOGLE")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
FREE_LLM_BASE_MODEL = os.getenv("FREE_LLM_BASE_MODEL")
FREE_LLM_MODEL_NAME = os.getenv("FREE_LLM_MODEL_NAME")
FREE_LLM_NUM_CTX = os.getenv("FREE_LLM_NUM_CTX")
FREE_LLM_TEMPERATURE = os.getenv("FREE_LLM_TEMPERATURE")
FREE_LLM_API_BASE_URL = os.getenv("FREE_LLM_API_BASE_URL")
FREE_LLM_API_KEY = os.getenv("FREE_LLM_API_KEY")

SERPER_API_KEY = os.getenv("SERPER_API_KEY")

MODEL_EMBBEDINGS_RAG = os.getenv("MODEL_EMBBEDINGS_RAG")

# Azure
AZURE_FORM_RECOGNIZER_ENDPOINT = os.getenv("AZURE_FORM_RECOGNIZER_ENDPOINT")
AZURE_FORM_RECOGNIZER_KEY = os.getenv("AZURE_FORM_RECOGNIZER_KEY")
AZURE_FORM_RECOGNIZER_MODEL_ID = os.getenv("AZURE_FORM_RECOGNIZER_MODEL_ID")

# PersistÃªncia
PERSISTENT_MEMORY_INDEX_PATH = os.getenv("PERSISTENT_MEMORY_INDEX_PATH")
PERSISTENT_MEMORY_METADATA_PATH = os.getenv("PERSISTENT_MEMORY_METADATA_PATH")
LOG_DIR = os.getenv("LOG_DIR")
DB_URI = os.getenv("DB_URI")
TMP_DIR = os.getenv("TMP_DIR", "agent/tmp")
UPLOADS_DIR = os.getenv("UPLOADS_DIR", f"{TMP_DIR}/uploads")
RAG_UPLOADS_DIR = os.getenv("RAG_UPLOADS_DIR", UPLOADS_DIR)

AGENT_CONFIG = os.getenv("AGENT_CONFIG", "templates/agent_template.json")
AUDIT_MODULE_CONFIG = os.getenv("AUDIT_MODULE_CONFIG", "templates/audit_module.json")
AGENT_INTERACTIONS_TABLE = os.getenv("AGENT_INTERACTIONS_TABLE", "agent_interactions")
AUDIT_BASE_IS_LOCAL = False
USE_LOCAL_FRONT_DB = False
RDS_HOST = os.getenv("RDS_HOST")
RDS_PORT = os.getenv("RDS_PORT", "5432")
RDS_DB = os.getenv("RDS_DB", "postgres")
RDS_USER = os.getenv("RDS_USER", "postgres")
RDS_PASSWORD = os.getenv("RDS_PASSWORD")

# AWS credentials
AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID")
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY")
AWS_DEFAULT_REGION = os.getenv("AWS_DEFAULT_REGION")

RDS_FRONT_HOST = os.getenv("RDS_FRONT_HOST", RDS_HOST)
RDS_FRONT_PORT = os.getenv("RDS_FRONT_PORT", str(RDS_PORT))
RDS_FRONT_DB = os.getenv("RDS_FRONT_DB", RDS_DB)
RDS_FRONT_USER = os.getenv("RDS_FRONT_USER", RDS_USER)
RDS_FRONT_PASSWORD = os.getenv("RDS_FRONT_PASSWORD", RDS_PASSWORD)
LOCAL_FRONT_DB_PATH = os.getenv("LOCAL_FRONT_DB_PATH", "front_local.db")
FASTAPI_ROOT_PATH = os.getenv("FASTAPI_ROOT_PATH")
RUNTIME_LOGS_DIR = os.getenv(
    "RUNTIME_LOGS_DIR",
    f"{TMP_DIR}/runtime_logs",
)
AI_REQUEST_TRACE_ENABLED = _parse_bool(os.getenv("AI_REQUEST_TRACE_ENABLED", "true"))
AI_REQUEST_TRACE_PREFIX = os.getenv("AI_REQUEST_TRACE_PREFIX", "observability/ai-runtime")
# Redis
REDIS_HOST = os.getenv("REDIS_HOST", "")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
REDIS_SSL = _parse_bool(os.getenv("REDIS_SSL", "false"))
USE_REDIS_CONTEXT = _parse_bool(os.getenv("USE_REDIS_CONTEXT", "true")) and bool(REDIS_HOST)
if USE_REDIS_CONTEXT:
    print(f"USANDO REDIS: {REDIS_HOST}:{REDIS_PORT}")
PREFERENCES_PER_SESSION = _parse_bool(os.getenv("PREFERENCES_PER_SESSION", "true"))
MAX_CONCURRENT_JOBS = 4
MAX_MEMORY_PERCENT = 80
JOB_TIMEOUT_SECONDS = 100
CHUNK_SIZE = 500
SESSION_TTL_SECONDS = 60 * 60 * 6  # 6h
LANGSMITH_PROJECT_ID = os.getenv("LANGSMITH_PROJECT_ID", "My First App")
LANGSMITH_TRACING = _parse_bool(os.getenv("LANGSMITH_TRACING", "true"))
LANGSMITH_ENDPOINT = os.getenv(
    "LANGSMITH_ENDPOINT", "https://api.smith.langchain.com"
)
LANGSMITH_API_KEY = os.getenv("LANGSMITH_API_KEY")
LANGSMITH_WORKSPACE_ID = os.getenv("LANGSMITH_WORKSPACE_ID", "QualityFinancasDev")
OTEL_SERVICE_NAME = os.getenv("OTEL_SERVICE_NAME", "agent-ai-orchestrator")
OTEL_EXPORTER_OTLP_ENDPOINT = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
OTEL_EXPORTER_OTLP_HEADERS = os.getenv("OTEL_EXPORTER_OTLP_HEADERS")
OTEL_EXPORTER_OTLP_INSECURE = _parse_bool(os.getenv("OTEL_EXPORTER_OTLP_INSECURE", "true"))
AUTOGEN_DISABLE_RUNTIME_TRACING = _parse_bool(
    os.getenv("AUTOGEN_DISABLE_RUNTIME_TRACING", "false")
)
SHOW_USAGE_LOGS = _parse_bool(os.getenv("SHOW_USAGE_LOGS", "false"))
SHOW_AGENT_INTERACTION_LOGS = _parse_bool(
    os.getenv("SHOW_AGENT_INTERACTION_LOGS", os.getenv("SHOW_AGENT_CHAT_LOGS", "false"))
)
SHOW_HISTORY_QUERY_PAYLOADS = _parse_bool(
    os.getenv("SHOW_HISTORY_QUERY_PAYLOADS", "false")
)

# Fast path do backend da IA.
# Por padrão, a conversa usa apenas o histórico recente do chat atual.
# Taxonomia, feedback agregado e memória estruturada podem ser reativados por
# ambiente quando fizerem sentido para um tenant/template específico.
ENABLE_RAG_TOOLKITS = _parse_bool(os.getenv("ENABLE_RAG_TOOLKITS", "false"))
REDIS_HISTORY_MAX_MESSAGES_PER_AGENT = int(
    os.getenv("REDIS_HISTORY_MAX_MESSAGES_PER_AGENT", "8")
)
CHAT_CONTEXT_MAX_INTERACTIONS = int(os.getenv("CHAT_CONTEXT_MAX_INTERACTIONS", "6"))

# Storage de arquivos / MinIO compativel com S3
FILE_STORAGE_ENDPOINT = os.getenv("FILE_STORAGE_ENDPOINT", "")
FILE_STORAGE_PUBLIC_ENDPOINT = os.getenv("FILE_STORAGE_PUBLIC_ENDPOINT", "")
FILE_STORAGE_ACCESS_KEY = os.getenv("FILE_STORAGE_ACCESS_KEY", "")
FILE_STORAGE_SECRET_KEY = os.getenv("FILE_STORAGE_SECRET_KEY", "")
FILE_STORAGE_BUCKET = os.getenv("FILE_STORAGE_BUCKET", "")
FILE_STORAGE_REGION = os.getenv("FILE_STORAGE_REGION", "us-east-1")
FILE_STORAGE_URL_MODE = os.getenv("FILE_STORAGE_URL_MODE", "permanent")
FILE_STORAGE_SIGNED_URL_EXPIRES_SECONDS = int(
    os.getenv("FILE_STORAGE_SIGNED_URL_EXPIRES_SECONDS", "86400")
)
