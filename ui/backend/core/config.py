import os
from pathlib import Path

from dotenv import load_dotenv


load_dotenv()

BASE_DIR = Path(__file__).resolve().parents[3]
FRONTEND_DIR = BASE_DIR / "ui" / "frontend"
MIGRATIONS_DIR = BASE_DIR / "db" / "migrations"

UI_DB_HOST = os.getenv("UI_DB_HOST", os.getenv("RDS_HOST", "postgres"))
UI_DB_PORT = int(os.getenv("UI_DB_PORT", os.getenv("RDS_PORT", "5432")))
UI_DB_NAME = os.getenv("UI_DB_NAME", os.getenv("RDS_DB", "agent_llm"))
UI_DB_USER = os.getenv("UI_DB_USER", os.getenv("RDS_USER", "postgres"))
UI_DB_PASSWORD = os.getenv("UI_DB_PASSWORD", os.getenv("RDS_PASSWORD", "postgres"))

UI_SESSION_HOURS = int(os.getenv("UI_SESSION_HOURS", "24"))
UI_SESSION_IDLE_MINUTES = int(os.getenv("UI_SESSION_IDLE_MINUTES", "120"))
UI_MASTER_EMAIL = os.getenv("UI_MASTER_EMAIL", "master@agent.local")
UI_MASTER_PASSWORD = os.getenv("UI_MASTER_PASSWORD", "admin123")
UI_MASTER_NAME = os.getenv("UI_MASTER_NAME", "Master Agent")
UI_MASTER_PHONE = os.getenv("UI_MASTER_PHONE", "")
UI_MASTER_ABOUT = os.getenv("UI_MASTER_ABOUT", "Administrador master do sistema")
UI_MASTER_TENANT_NAME = os.getenv("UI_MASTER_TENANT_NAME", "Agent Demo")
UI_MASTER_TENANT_LEGAL_NAME = os.getenv("UI_MASTER_TENANT_LEGAL_NAME", "Agent Demo Ltda")
UI_MASTER_TENANT_CNPJ = os.getenv("UI_MASTER_TENANT_CNPJ", "")

AI_API_BASE_URL = os.getenv("AI_API_BASE_URL", "http://agent:8080")
AI_API_ROOT_PATH = os.getenv("AI_API_ROOT_PATH", os.getenv("FASTAPI_ROOT_PATH", ""))
AI_DEFAULT_MODULE = os.getenv("AI_DEFAULT_MODULE", "Finances")
AI_DEFAULT_TENANT_ID = os.getenv("AI_DEFAULT_TENANT_ID", "quality_financas")

REDIS_HOST = os.getenv("REDIS_HOST", "redis")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
REDIS_SSL = os.getenv("REDIS_SSL", "false").strip().lower() in {"1", "true", "yes", "on"}

LEGACY_AGENT_TEMPLATE_PATH = os.getenv("AGENT_CONFIG", "templates/agent_template.json")

FILE_STORAGE_ENDPOINT = os.getenv("FILE_STORAGE_ENDPOINT", "http://minio:9000").rstrip("/")
FILE_STORAGE_PUBLIC_ENDPOINT = os.getenv("FILE_STORAGE_PUBLIC_ENDPOINT", "http://localhost:9000").rstrip("/")
FILE_STORAGE_ACCESS_KEY = os.getenv("FILE_STORAGE_ACCESS_KEY", "agentminio")
FILE_STORAGE_SECRET_KEY = os.getenv("FILE_STORAGE_SECRET_KEY", "agentminio123")
FILE_STORAGE_BUCKET = os.getenv("FILE_STORAGE_BUCKET", "agent-files")
FILE_STORAGE_REGION = os.getenv("FILE_STORAGE_REGION", "us-east-1")
FILE_STORAGE_URL_MODE = os.getenv("FILE_STORAGE_URL_MODE", "permanent").strip().lower()
FILE_STORAGE_SIGNED_URL_EXPIRES_SECONDS = int(os.getenv("FILE_STORAGE_SIGNED_URL_EXPIRES_SECONDS", "86400"))
