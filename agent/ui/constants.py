from pathlib import Path
import config as settings

BASE_PATH = Path(__file__).resolve().parents[2]
JSON_PATH = BASE_PATH / settings.AGENT_CONFIG
TOOLS_PATH = BASE_PATH / "agent" / "tools"
RAG_PATH = BASE_PATH / "agent" / "knowledge"

ALLOWED_TYPES = [
    "UserProxyAgent",
    "AssistantAgent",
]
