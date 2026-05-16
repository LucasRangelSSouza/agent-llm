import json
import re
import time
import unicodedata
from typing import Any, Dict, List, Optional

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.language_models.chat_models import BaseChatModel

import config as settings
from agent.infrastructure.runtime.ai_service import normalize_provider


MEMORY_TTL_SECONDS = 60 * 60 * 24 * 90  # 90 dias
LAST_INTERACTION_TTL_SECONDS = 60 * 60 * 24 * 7  # 7 dias
SESSION_SUMMARY_TTL_SECONDS = 60 * 60 * 24 * 30  # 30 dias
SESSION_CONTEXT_TTL_SECONDS = 60 * 60 * 24 * 30  # 30 dias


def normalize_rating(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    norm = value.strip().lower()
    if norm in {"positive", "pos", "up", "good", "👍", "like"}:
        return "positive"
    if norm in {"negative", "neg", "down", "bad", "👎", "dislike"}:
        return "negative"
    return None


def resolve_memory_scope(tenant_id: str, user_id: str, session_id: str) -> Optional[str]:
    scope_user = None
    use_session = bool(
        settings.PREFERENCES_PER_SESSION
        and session_id
        and session_id != "unknown"
    )
    if use_session:
        scope_user = session_id
    elif user_id and user_id != "unknown":
        scope_user = user_id
    elif session_id and session_id != "unknown":
        scope_user = session_id
    if not scope_user:
        return None
    tenant = tenant_id or "default"
    return f"{tenant}:{scope_user}"


def resolve_session_scope(tenant_id: str, session_id: str) -> Optional[str]:
    if not session_id or session_id == "unknown":
        return None
    tenant = tenant_id or "default"
    return f"{tenant}:session:{session_id}"


def memory_key(scope: str) -> str:
    return f"memory:{scope}:v1"


def last_interaction_key(scope: str) -> str:
    return f"memory:{scope}:last_interaction"


def session_summary_key(scope: str) -> str:
    return f"memory:{scope}:session_summary"


def session_context_key(scope: str) -> str:
    return f"memory:{scope}:session_context"


def default_memory() -> Dict[str, Any]:
    return {
        "profile": {
            "facts": [],
            "preferences": [],
            "style": [],
        },
        "procedural": {
            "repeat": [],
            "avoid": [],
            "improve": [],
        },
        "updated_at": None,
    }


def load_user_memory(redis_client, scope: str) -> Dict[str, Any]:
    raw = redis_client.get(memory_key(scope))
    if not raw:
        return default_memory()
    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return default_memory()


def save_user_memory(redis_client, scope: str, memory: Dict[str, Any]) -> None:
    memory["updated_at"] = int(time.time())
    redis_client.set(
        memory_key(scope),
        json.dumps(memory, ensure_ascii=False),
        ex=MEMORY_TTL_SECONDS,
    )


def load_last_interaction(redis_client, scope: str) -> Optional[Dict[str, Any]]:
    raw = redis_client.get(last_interaction_key(scope))
    if not raw:
        return None
    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            return data
    except Exception:
        return None
    return None


def load_session_summary(redis_client, scope: str) -> List[str]:
    raw = redis_client.get(session_summary_key(scope))
    if not raw:
        return []
    try:
        data = json.loads(raw)
        if isinstance(data, list):
            return [str(x) for x in data if x]
    except Exception:
        return []
    return []


def load_session_context(redis_client, scope: str) -> Dict[str, Any]:
    raw = redis_client.get(session_context_key(scope))
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            return data
    except Exception:
        return {}
    return {}


def save_last_interaction(
    redis_client,
    scope: str,
    *,
    question: str,
    answer: str,
) -> None:
    payload = {
        "question": question,
        "answer": answer,
        "timestamp": int(time.time()),
    }
    redis_client.set(
        last_interaction_key(scope),
        json.dumps(payload, ensure_ascii=False),
        ex=LAST_INTERACTION_TTL_SECONDS,
    )


def save_session_summary(redis_client, scope: str, summary: List[str]) -> None:
    clean = [s for s in summary if isinstance(s, str) and s.strip()]
    redis_client.set(
        session_summary_key(scope),
        json.dumps(clean, ensure_ascii=False),
        ex=SESSION_SUMMARY_TTL_SECONDS,
    )


def save_session_context(redis_client, scope: str, context: Dict[str, Any]) -> None:
    payload = context if isinstance(context, dict) else {}
    payload["updated_at"] = int(time.time())
    redis_client.set(
        session_context_key(scope),
        json.dumps(payload, ensure_ascii=False),
        ex=SESSION_CONTEXT_TTL_SECONDS,
    )


def clear_session_summary(redis_client, scope: str) -> None:
    if not redis_client or not scope:
        return
    redis_client.delete(session_summary_key(scope))


def clear_session_context(redis_client, scope: str) -> None:
    if not redis_client or not scope:
        return
    redis_client.delete(session_context_key(scope))


def clear_last_interaction(redis_client, scope: str) -> None:
    if not redis_client or not scope:
        return
    redis_client.delete(last_interaction_key(scope))


def build_llm(ai_service: Optional[Dict[str, Any]] = None) -> Optional[BaseChatModel]:
    provider = normalize_provider((ai_service or {}).get("provider"))
    config = (ai_service or {}).get("config") or {}
    secret = (ai_service or {}).get("secret") or {}
    model_name = (ai_service or {}).get("model_name") or ""

    if provider == "gemini":
        from langchain_google_genai import ChatGoogleGenerativeAI

        api_key = secret.get("api_key")
        if not api_key:
            return None
        return ChatGoogleGenerativeAI(
            model=model_name or "gemini-2.5-flash",
            temperature=0,
            google_api_key=api_key,
        )

    if provider == "local_gguf":
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(
            model=model_name or getattr(settings, "FREE_LLM_MODEL_NAME", "") or "agent-free-qwen",
            temperature=0,
            api_key=secret.get("api_key") or getattr(settings, "FREE_LLM_API_KEY", "") or "ollama",
            base_url=config.get("endpoint_url") or getattr(settings, "FREE_LLM_API_BASE_URL", ""),
        )

    if provider == "claude":
        from langchain_anthropic import ChatAnthropic

        api_key = secret.get("api_key")
        if not api_key:
            return None
        kwargs = {
            "model": model_name or "claude-3-7-sonnet-latest",
            "temperature": 0,
            "api_key": api_key,
        }
        if config.get("endpoint_url"):
            kwargs["base_url"] = config["endpoint_url"]
        return ChatAnthropic(**kwargs)

    api_key = secret.get("api_key")
    if not api_key:
        return None
    from langchain_openai import ChatOpenAI

    kwargs = {
        "model": model_name or "gpt-4o-mini",
        "temperature": 0,
        "api_key": api_key,
    }
    if config.get("endpoint_url"):
        kwargs["base_url"] = config["endpoint_url"]
    if config.get("organization_id"):
        kwargs["organization"] = config["organization_id"]
    return ChatOpenAI(**kwargs)


def _safe_json_parse(text: str) -> Dict[str, Any]:
    if not text:
        return {}
    try:
        return json.loads(text)
    except Exception:
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except Exception:
            return {}
    return {}


def _normalize_for_trigger(text: Optional[str]) -> str:
    if not text:
        return ""
    normalized = unicodedata.normalize("NFKD", text)
    ascii_text = normalized.encode("ascii", "ignore").decode("utf-8", "ignore")
    return re.sub(r"\s+", " ", ascii_text).strip().lower()


_CLEAR_PREFERENCES_ACTIONS = {
    "excluir",
    "esquecer",
    "limpar",
    "apagar",
    "remover",
    "zerar",
    "resetar",
    "descartar",
    "eliminar",
}

_PREFERENCE_KEYWORDS = {"preferencia", "preferencias"}


def should_clear_preferences(message: Optional[str]) -> bool:
    normalized = _normalize_for_trigger(message)
    if not normalized:
        return False
    if not any(keyword in normalized for keyword in _PREFERENCE_KEYWORDS):
        return False
    return any(action in normalized for action in _CLEAR_PREFERENCES_ACTIONS)


def clear_preferences(memory: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    target = memory if isinstance(memory, dict) else default_memory()
    profile = target.setdefault("profile", {})
    profile["preferences"] = []
    return target


def _normalize_item(item: str) -> str:
    return " ".join(item.strip().lower().split())


def _clip_text(text: str, max_len: int) -> str:
    if not text:
        return ""
    if len(text) <= max_len:
        return text
    return text[: max_len - 3] + "..."


def _is_followup_question(question: str) -> bool:
    if not question:
        return False
    q = " ".join(question.strip().lower().split())
    if not q:
        return False
    followup_markers = [
        "e a previsao",
        "e a projeção",
        "e a projecao",
        "e o forecast",
        "previsao para",
        "projecao para",
        "forecast para",
        "e o ordenado",
        "e o salario",
        "e o salário",
        "e ele",
        "e dele",
        "e agora",
        "e esse",
        "e essa",
        "e isso",
        "poderia gerar",
        "pode gerar",
        "poderia fazer",
    ]
    if q.startswith("e "):
        return True
    return any(marker in q for marker in followup_markers)


def _merge_unique(existing: List[str], new_items: List[str], max_items: int) -> List[str]:
    seen = {_normalize_item(x) for x in existing if isinstance(x, str)}
    for item in new_items:
        if not isinstance(item, str):
            continue
        cleaned = item.strip()
        if not cleaned:
            continue
        norm = _normalize_item(cleaned)
        if norm in seen:
            continue
        existing.append(cleaned)
        seen.add(norm)
    if len(existing) > max_items:
        existing = existing[-max_items:]
    return existing


def format_memory_for_prompt(memory: Dict[str, Any]) -> str:
    if not memory:
        return ""
    profile = memory.get("profile", {})
    procedural = memory.get("procedural", {})

    lines: List[str] = []
    facts = profile.get("facts") or []
    prefs = profile.get("preferences") or []
    style = profile.get("style") or []
    repeat = procedural.get("repeat") or []
    avoid = procedural.get("avoid") or []
    improve = procedural.get("improve") or []

    if facts:
        lines.append("Fatos do usuario: " + "; ".join(facts[:8]))
    if prefs:
        lines.append("Preferencias: " + "; ".join(prefs[:8]))
    if style:
        lines.append("Estilo preferido: " + "; ".join(style[:8]))
    if repeat:
        lines.append("Repetir quando possivel: " + "; ".join(repeat[:6]))
    if avoid:
        lines.append("Evitar: " + "; ".join(avoid[:6]))
    if improve:
        lines.append("Melhorias desejadas: " + "; ".join(improve[:6]))

    return "\n".join(lines).strip()


def format_last_interaction(last: Optional[Dict[str, Any]]) -> str:
    if not last:
        return ""
    question = _clip_text(str(last.get("question", "")), 400)
    answer = _clip_text(str(last.get("answer", "")), 400)
    if not question and not answer:
        return ""
    lines = ["Ultima conversa (use apenas para desambiguar follow-ups):"]
    if question:
        lines.append(f"- Pergunta: {question}")
    if answer:
        lines.append(f"- Resposta: {answer}")
    return "\n".join(lines)


def format_session_summary(summary: List[str]) -> str:
    if not summary:
        return ""
    clean = [s.strip() for s in summary if isinstance(s, str) and s.strip()]
    if not clean:
        return ""
    joined = "; ".join(clean[:8])
    return f"Resumo do chat (alto nivel): {joined}"


def format_session_context(context: Dict[str, Any]) -> str:
    if not context:
        return ""
    label = str(context.get("label", "") or "").strip()
    changed = context.get("changed")
    notes = context.get("notes") or []
    lines: List[str] = []
    if label:
        lines.append(f"Contexto identificado: {label}")
    if isinstance(changed, bool):
        lines.append(f"Mudou de contexto: {str(changed).lower()}")
    if isinstance(notes, list) and notes:
        clean = [str(n).strip() for n in notes if str(n).strip()]
        if clean:
            lines.append("Informacoes do contexto: " + "; ".join(clean[:6]))
    return "\n".join(lines).strip()


def build_memory_context(
    *,
    user_memory: Optional[Dict[str, Any]] = None,
    last_interaction: Optional[Dict[str, Any]] = None,
    session_summary: Optional[List[str]] = None,
    session_context: Optional[Dict[str, Any]] = None,
) -> str:
    lines: List[str] = []
    last_block = format_last_interaction(last_interaction)
    if last_block:
        lines.append(last_block)

    summary_block = format_session_summary(session_summary or [])
    if summary_block:
        lines.append(summary_block)

    context_block = format_session_context(session_context or {})
    if context_block:
        lines.append(context_block)

    if user_memory:
        user_block = format_memory_for_prompt(user_memory)
        if user_block:
            lines.append("Preferencias do usuario (longo prazo):")
            lines.append(user_block)

    return "\n".join(lines).strip()


def inject_memory_into_question(question: str, memory_context: str) -> str:
    if not memory_context:
        return question
    try:
        preview = memory_context.replace("\n", " ")[:200]
        print(f"🧠 auto_memory injetando contexto: {preview}{'...' if len(memory_context) > 200 else ''}")
    except Exception:
        pass
    return (
        "INSTRUCOES INTERNAS (NAO MOSTRAR AO USUARIO):\n"
        "Use esta memoria apenas para ajustar estilo e foco. "
        "Use 'Ultima conversa' e 'Resumo do chat' apenas se a pergunta atual for ambigua. "
        "Se houver 'Contexto identificado', use APENAS esse contexto na resposta. "
        "Se houver conflito com a pergunta atual, pergunte para esclarecer. "
        "NAO resuma, NAO mencione feedbacks, NAO liste Manter/Melhorar/Evitar.\n"
        f"{memory_context}\n\n"
        "Pergunta do usuario:\n"
        f"{question}"
    )


def update_session_summary(
    llm: BaseChatModel,
    *,
    prior_summary: List[str],
    question: str,
    answer: str,
) -> List[str]:
    if not llm or not question or not answer:
        return prior_summary or []
    system_prompt = (
        "Voce atualiza o resumo do chat. Retorne APENAS JSON valido no formato: "
        '{"summary": []}\n'
        "O resumo deve ter no maximo 6 itens curtos, em portugues, alto nivel, "
        "sem numeros detalhados e sem citar feedbacks. "
        "Use o resumo anterior como base e atualize apenas com informacao relevante."
    )
    human_prompt = (
        f"Resumo anterior:\n{json.dumps(prior_summary, ensure_ascii=False)}\n\n"
        f"Pergunta:\n{question}\n\n"
        f"Resposta:\n{answer}\n"
    )
    response = llm.invoke(
        [
            SystemMessage(content=system_prompt),
            HumanMessage(content=human_prompt),
        ]
    )
    content = getattr(response, "content", "") or ""
    data = _safe_json_parse(content)
    summary = data.get("summary") if isinstance(data, dict) else None
    if isinstance(summary, list):
        clean = [str(s).strip() for s in summary if str(s).strip()]
        return clean[:6]
    return prior_summary or []


def update_session_context(
    llm: BaseChatModel, *, prior_context: Dict[str, Any], question: str
) -> Dict[str, Any]:
    if not question:
        return prior_context or {}
    if prior_context and _is_followup_question(question):
        return {
            "label": str(prior_context.get("label", "") or "").strip(),
            "changed": False,
            "notes": prior_context.get("notes") or [],
        }
    if not llm:
        return prior_context or {}
    system_prompt = (
        "Voce identifica o contexto atual da conversa. Retorne APENAS JSON valido no formato:\n"
        '{"changed": true|false, "label": "", "notes": []}\n'
        "Regras:\n"
        "- label curto (max 8 palavras), ex.: \"custo pessoal ITO 2025\" ou \"funcionario Clovis 2025\".\n"
        "- notes: 1 a 4 itens curtos com filtros importantes (ano, unidade, pessoa, indicador).\n"
        "- changed = true se o contexto atual for diferente do anterior.\n"
        "- Nao invente dados.\n"
    )
    human_prompt = (
        f"Contexto anterior (JSON):\n{json.dumps(prior_context or {}, ensure_ascii=False)}\n\n"
        f"Pergunta atual:\n{question}\n"
    )
    response = llm.invoke(
        [
            SystemMessage(content=system_prompt),
            HumanMessage(content=human_prompt),
        ]
    )
    content = getattr(response, "content", "") or ""
    data = _safe_json_parse(content)
    if not isinstance(data, dict):
        return prior_context or {}
    label = str(data.get("label", "") or "").strip()
    changed = data.get("changed")
    notes = data.get("notes") if isinstance(data.get("notes"), list) else []
    prior_label = str((prior_context or {}).get("label", "") or "").strip()
    if prior_label and label and (label == prior_label or prior_label in label):
        changed = False
    return {
        "label": label,
        "changed": bool(changed) if isinstance(changed, bool) else False,
        "notes": notes,
    }


def extract_profile_updates(llm: BaseChatModel, user_message: str) -> Dict[str, Any]:
    if not user_message or not llm:
        return {}
    system_prompt = (
        "Voce extrai memorias de longo prazo. Guarde apenas fatos estaveis sobre o usuario "
        "e preferencias explicitas (ex.: nome, idioma, estilo). Nao guarde dados sensiveis, "
        "segredos, ou informacoes temporarias. Responda APENAS com JSON valido no formato:\n"
        '{"facts": [], "preferences": [], "style": []}\n'
        "Se nao houver nada relevante, retorne listas vazias."
    )
    response = llm.invoke(
        [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_message),
        ]
    )
    content = getattr(response, "content", "") or ""
    return _safe_json_parse(content)


def extract_feedback_updates(
    llm: BaseChatModel, *, question: str, answer: str, rating: str
) -> Dict[str, Any]:
    if not llm or not question or not answer or rating not in {"positive", "negative"}:
        return {}
    system_prompt = (
        "Voce transforma feedback em memoria procedural. Use apenas o que esta no dialogo. "
        "Retorne APENAS JSON valido com as chaves:\n"
        '{"repeat": [], "avoid": [], "improve": []}\n'
        "Se o feedback for positive, foque em 'repeat'. Se for negative, foque em 'avoid' e 'improve'. "
        "Nao invente preferencias."
    )
    human_prompt = (
        f"Feedback: {rating}\n\n"
        f"Pergunta:\n{question}\n\n"
        f"Resposta:\n{answer}\n"
    )
    response = llm.invoke(
        [
            SystemMessage(content=system_prompt),
            HumanMessage(content=human_prompt),
        ]
    )
    content = getattr(response, "content", "") or ""
    return _safe_json_parse(content)


def apply_profile_updates(memory: Dict[str, Any], updates: Dict[str, Any]) -> Dict[str, Any]:
    if not updates:
        return memory
    profile = memory.setdefault("profile", {})
    profile["facts"] = _merge_unique(profile.get("facts", []), updates.get("facts", []), 80)
    profile["preferences"] = _merge_unique(
        profile.get("preferences", []), updates.get("preferences", []), 80
    )
    profile["style"] = _merge_unique(profile.get("style", []), updates.get("style", []), 40)
    return memory


def apply_feedback_updates(memory: Dict[str, Any], updates: Dict[str, Any]) -> Dict[str, Any]:
    if not updates:
        return memory
    procedural = memory.setdefault("procedural", {})
    procedural["repeat"] = _merge_unique(
        procedural.get("repeat", []), updates.get("repeat", []), 60
    )
    procedural["avoid"] = _merge_unique(
        procedural.get("avoid", []), updates.get("avoid", []), 60
    )
    procedural["improve"] = _merge_unique(
        procedural.get("improve", []), updates.get("improve", []), 60
    )
    return memory
