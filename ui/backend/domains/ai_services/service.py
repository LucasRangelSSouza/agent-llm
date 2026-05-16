from typing import Any, Dict, List


SUPPORTED_AI_PROVIDERS: List[Dict[str, Any]] = [
    {
        "value": "openai",
        "label": "OpenAI",
        "requires_api_key": True,
        "models": ["gpt-5.2", "gpt-5.1", "gpt-4o-mini"],
    },
    {
        "value": "claude",
        "label": "Claude",
        "requires_api_key": True,
        "models": ["claude-sonnet-4", "claude-3-7-sonnet-latest", "claude-3-5-haiku-latest"],
    },
    {
        "value": "gemini",
        "label": "Gemini",
        "requires_api_key": True,
        "models": ["gemini-2.5-flash", "gemini-2.5-pro", "gemini-2.0-flash"],
    },
    {
        "value": "grok",
        "label": "Grok",
        "requires_api_key": True,
        "models": ["grok-3-mini", "grok-3-fast", "grok-2-latest"],
    },
    {
        "value": "deepseek",
        "label": "DeepSeek",
        "requires_api_key": True,
        "models": ["deepseek-chat", "deepseek-reasoner", "deepseek-v3"],
    },
    {
        "value": "local_gguf",
        "label": "Local GGUF",
        "requires_api_key": False,
        "models": ["Qwen2.5-3B-Instruct-GGUF", "Llama-3.2-3B-Instruct-GGUF", "Gemma-2-2B-It-GGUF"],
    },
]

SUPPORTED_PROVIDER_MAP = {item["value"]: item for item in SUPPORTED_AI_PROVIDERS}


def require_ai_service_manager(current_user: dict) -> None:
    if current_user.get("role") == "master":
        return
    if not current_user.get("permissions", {}).get("ai_services", {}).get("view"):
        raise PermissionError("Usuario sem permissao nesse recurso")


def get_ai_service_catalog() -> Dict[str, Any]:
    return {"providers": SUPPORTED_AI_PROVIDERS}


def _clean(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def build_ai_service_payload(payload: Dict[str, Any], current_user: dict, existing: Dict[str, Any] | None = None):
    require_ai_service_manager(current_user)

    provider = _clean(payload.get("provider")).lower()
    if provider not in SUPPORTED_PROVIDER_MAP:
        raise ValueError("Provider de IA nao suportado.")

    tenant_id = _clean(payload.get("tenant_id")) or current_user["tenant_id"]
    if current_user["role"] != "master":
        tenant_id = current_user["tenant_id"]

    existing_config = (existing or {}).get("config_json") or {}
    existing_secret = (existing or {}).get("secret_json") or {}

    name = _clean(payload.get("name"))
    model_name = _clean(payload.get("model_name"))
    description = _clean(payload.get("description"))
    api_key = _clean(payload.get("api_key")) or existing_secret.get("api_key", "")
    endpoint_url = _clean(payload.get("endpoint_url")) or existing_config.get("endpoint_url", "")
    organization_id = _clean(payload.get("organization_id")) or existing_config.get("organization_id", "")
    is_active = bool(payload.get("is_active", True))

    if not name:
        raise ValueError("Informe um nome para o servico de IA.")
    if not model_name:
        raise ValueError("Informe o modelo principal deste servico.")
    if SUPPORTED_PROVIDER_MAP[provider]["requires_api_key"] and not api_key:
        raise ValueError("A chave de API e obrigatoria para este provider.")

    config_json = {
        "provider": provider,
        "endpoint_url": endpoint_url,
        "organization_id": organization_id,
        "suggested_models": SUPPORTED_PROVIDER_MAP[provider]["models"],
    }
    secret_json = {"api_key": api_key}
    meta = {
        "tenant_id": tenant_id,
        "provider": provider,
        "name": name,
        "description": description,
        "model_name": model_name,
        "is_active": is_active,
    }
    return tenant_id, config_json, secret_json, meta


def _mask_secret(secret_value: str) -> str:
    if not secret_value:
        return ""
    if len(secret_value) <= 6:
        return "*" * len(secret_value)
    return f"{secret_value[:3]}***{secret_value[-3:]}"


def serialize_ai_service(row: Dict[str, Any], include_edit_payload: bool = False) -> Dict[str, Any]:
    config_json = row.get("config_json") or {}
    secret_json = row.get("secret_json") or {}
    provider_info = SUPPORTED_PROVIDER_MAP.get(row["provider"], {})

    item = {
        "id": row["id"],
        "tenant_id": row["tenant_id"],
        "tenant_name": row.get("tenant_name"),
        "provider": row["provider"],
        "provider_label": provider_info.get("label", row["provider"]),
        "name": row["name"],
        "description": row.get("description") or "",
        "model_name": row.get("model_name") or "",
        "is_active": row.get("is_active", True),
        "api_key": secret_json.get("api_key", ""),
        "created_at": row["created_at"].isoformat() if row.get("created_at") else None,
        "updated_at": row["updated_at"].isoformat() if row.get("updated_at") else None,
    }

    if include_edit_payload:
        item["form"] = {
            "name": row["name"],
            "provider": row["provider"],
            "description": row.get("description") or "",
            "model_name": row.get("model_name") or "",
            "tenant_id": row["tenant_id"],
            "is_active": row.get("is_active", True),
            "api_key": secret_json.get("api_key", ""),
            "endpoint_url": config_json.get("endpoint_url", ""),
            "organization_id": config_json.get("organization_id", ""),
            "has_api_key": bool(secret_json.get("api_key")),
            "api_key_preview": _mask_secret(secret_json.get("api_key", "")),
        }

    return item
