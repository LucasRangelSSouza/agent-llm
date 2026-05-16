import json
from datetime import datetime
from zoneinfo import ZoneInfo

from agent.modules.db.audit_db import AuditDB

TZ_BR = ZoneInfo("America/Sao_Paulo")


def build_log(
    session_id: str,
    user_id: str,
    customer_id: str,
    chat_id: str,
    group_chat,
    user_question,
    log_dir,
    module_name,
    is_local=False,
    user_name="unknown",
):
    if not hasattr(group_chat, "messages") or not group_chat.messages:
        return

    last_msg = group_chat.messages[-1]
    interaction_time = datetime.now(TZ_BR).isoformat()

    try:
        db = AuditDB(tenant_id=customer_id, is_local=is_local)
        db.insert_interaction(
            tenant_id=customer_id,
            chat_id=chat_id,
            session_id=session_id,
            user_id=user_id,
            user_name=user_name,
            interaction_time=interaction_time,
            user_question=user_question,
            agent_name=last_msg.get("name", "unknown"),
            content=last_msg.get("content", ""),
            module_name=module_name,
            source="ai_runtime",
        )
    except Exception as error:
        print(f"Erro ao sincronizar log com banco: {error}")
