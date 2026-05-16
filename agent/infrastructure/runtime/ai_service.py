from __future__ import annotations

from typing import Any, Dict, Optional

from autogen import AssistantAgent
from autogen.agentchat.contrib.multimodal_conversable_agent import MultimodalConversableAgent

import config as settings


RuntimeAIService = Dict[str, Any]


def normalize_provider(provider: Optional[str]) -> str:
    value = (provider or "").strip().lower()
    if value in {"anthropic", "claude"}:
        return "claude"
    if value in {"google", "gemini"}:
        return "gemini"
    if value in {"openai", "local_gguf"}:
        return value
    return value or "openai"


def fallback_ai_service() -> RuntimeAIService:
    return {
        "provider": "local_gguf",
        "name": "Free LLM",
        "model_name": getattr(settings, "FREE_LLM_MODEL_NAME", "") or "agent-free-qwen",
        "config": {
            "endpoint_url": getattr(settings, "FREE_LLM_API_BASE_URL", "") or "http://free-llm:11434/v1",
        },
        "secret": {"api_key": getattr(settings, "FREE_LLM_API_KEY", "") or "ollama"},
    }


def resolve_ai_service(agent_template: Optional[dict], module_name: Optional[str] = None) -> RuntimeAIService:
    if not isinstance(agent_template, dict):
        return fallback_ai_service()

    if module_name:
        module_config = agent_template.get(module_name) or {}
        ai_service = module_config.get("ai_service")
        if isinstance(ai_service, dict) and ai_service:
            return _normalize_ai_service(ai_service)

    for _, module_config in agent_template.items():
        if not isinstance(module_config, dict):
            continue
        ai_service = module_config.get("ai_service")
        if isinstance(ai_service, dict) and ai_service:
            return _normalize_ai_service(ai_service)

    return fallback_ai_service()


def _normalize_ai_service(ai_service: dict) -> RuntimeAIService:
    config = dict(ai_service.get("config") or {})
    secret = dict(ai_service.get("secret") or {})
    normalized = {
        **ai_service,
        "provider": normalize_provider(ai_service.get("provider")),
        "model_name": (ai_service.get("model_name") or "").strip(),
        "config": config,
        "secret": secret,
    }

    if normalized["provider"] == "local_gguf":
        config.setdefault(
            "endpoint_url",
            getattr(settings, "FREE_LLM_API_BASE_URL", "") or "http://free-llm:11434/v1",
        )
        secret.setdefault(
            "api_key",
            getattr(settings, "FREE_LLM_API_KEY", "") or "ollama",
        )
        if not normalized["model_name"]:
            normalized["model_name"] = getattr(settings, "FREE_LLM_MODEL_NAME", "") or "agent-free-qwen"

    return normalized


def build_autogen_config_entry(
    ai_service: Optional[RuntimeAIService],
    *,
    model_override: Optional[str] = None,
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
    seed: Optional[int] = None,
) -> Dict[str, Any]:
    service = _normalize_ai_service(ai_service or fallback_ai_service())
    provider = service["provider"]
    config = service.get("config") or {}
    secret = service.get("secret") or {}
    model_name = (model_override or service.get("model_name") or "").strip()

    entry: Dict[str, Any]
    if provider == "gemini":
        entry = {
            "api_type": "google",
            "model": model_name or "gemini-2.5-flash",
            "api_key": secret.get("api_key"),
        }
    elif provider == "claude":
        entry = {
            "api_type": "anthropic",
            "model": model_name or "claude-3-7-sonnet-latest",
            "api_key": secret.get("api_key"),
        }
        if config.get("endpoint_url"):
            entry["base_url"] = config["endpoint_url"]
    else:
        endpoint_url = config.get("endpoint_url")
        api_key = secret.get("api_key")
        if provider == "local_gguf":
            endpoint_url = endpoint_url or getattr(settings, "FREE_LLM_API_BASE_URL", "")
            api_key = api_key or getattr(settings, "FREE_LLM_API_KEY", "") or "ollama"
            model_name = model_name or getattr(settings, "FREE_LLM_MODEL_NAME", "") or "agent-free-qwen"

        entry = {
            "api_type": "openai",
            "model": model_name or "gpt-4o-mini",
            "api_key": api_key,
        }
        if endpoint_url:
            entry["base_url"] = endpoint_url
        if config.get("organization_id"):
            entry["organization"] = config["organization_id"]

    if temperature is not None:
        entry["temperature"] = temperature
    if max_tokens is not None:
        entry["max_tokens"] = max_tokens
    if seed is not None:
        entry["seed"] = seed
    return entry


def build_autogen_llm_config(
    ai_service: Optional[RuntimeAIService],
    *,
    model_override: Optional[str] = None,
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
    seed: Optional[int] = None,
) -> Dict[str, Any]:
    return {
        "config_list": [
            build_autogen_config_entry(
                ai_service,
                model_override=model_override,
                temperature=temperature,
                max_tokens=max_tokens,
                seed=seed,
            )
        ]
    }


def create_assistant_agent(
    *,
    name: str,
    system_message: str,
    ai_service: Optional[RuntimeAIService],
    human_input_mode: str = "NEVER",
) -> AssistantAgent:
    return AssistantAgent(
        name=name,
        system_message=system_message,
        llm_config=build_autogen_llm_config(ai_service),
        human_input_mode=human_input_mode,
    )


def create_multimodal_agent(
    *,
    name: str,
    system_message: str,
    ai_service: Optional[RuntimeAIService],
    human_input_mode: str = "NEVER",
) -> MultimodalConversableAgent:
    return MultimodalConversableAgent(
        name=name,
        system_message=system_message,
        llm_config=build_autogen_llm_config(ai_service),
        human_input_mode=human_input_mode,
    )


def generate_text_reply(
    *,
    name: str,
    system_message: str,
    user_message: str,
    ai_service: Optional[RuntimeAIService],
    model_override: Optional[str] = None,
) -> str:
    agent = AssistantAgent(
        name=name,
        system_message=system_message,
        llm_config=build_autogen_llm_config(ai_service, model_override=model_override),
        human_input_mode="NEVER",
    )
    reply = agent.generate_reply(messages=[{"role": "user", "content": user_message}])
    if isinstance(reply, str):
        return reply
    return getattr(reply, "content", str(reply))
