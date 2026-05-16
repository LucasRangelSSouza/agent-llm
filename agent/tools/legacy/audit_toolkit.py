import json
import logging
import os
import re
from datetime import date

import config as settings
from agent.modules.db.audit_db import AuditDB
from agent.tools.audit_query_agent import AuditQueryAgent
from agent.tools.audit_sql_utils import (
    execute_with_retries,
    translate_date,
    translate_datetime,
    translate_group_concat,
    translate_time_comparison,
)

logger = logging.getLogger(__name__)


class AuditToolkit:
    """Toolkit compatível com Autogen para consultas de auditoria."""

    GENERAL_KEYWORDS = [
        "ultimas interacoes",
        "interacoes recentes",
        "ultimos registros",
        "interacoes por ordem decrescente",
    ]

    RESULT_PREFIX = "Resultado encontrado:"

    def __init__(self, tenant_id: str, db_path=None, model="gpt-4o-mini", ai_service=None):
        self.tenant_id = tenant_id
        self.ai_service = ai_service

        if settings.AUDIT_BASE_IS_LOCAL:
            if db_path is None:
                base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../.."))
                db_path = os.path.join(base_dir, "audit.db")
            self.db = AuditDB(
                tenant_id=tenant_id,
                db_path=db_path,
                is_local=settings.AUDIT_BASE_IS_LOCAL,
            )
        else:
            self.db = AuditDB(tenant_id=tenant_id, is_local=settings.AUDIT_BASE_IS_LOCAL)

        self.agent = AuditQueryAgent(self.db, model=model, ai_service=ai_service)

    def _format_result(self, result):
        if isinstance(result, str):
            if not result.strip():
                return "Nenhum resultado encontrado na auditoria."
            parsed = self._parse_json_result(result)
            if isinstance(parsed, list) and parsed:
                self._ensure_user_names(parsed)
                return self._format_table(parsed)
            return result

        if isinstance(result, list):
            if not result:
                return "Nenhuma interacao encontrada."

            self._ensure_user_names(result)
            formatted = []
            for row in result[:5]:
                interaction_time = row.get("interaction_time", "--")
                agent_name = row.get("agent_name") or row.get("agent") or "--"
                user_name = row.get("user_name")
                user_id = row.get("user_id", "--")
                display_user = user_name or user_id
                formatted.append(
                    f"- {interaction_time} | {display_user} -> {agent_name}\n"
                    f"  Pergunta: {row.get('user_question', '-')}\n"
                    f"  Resposta: {str(row.get('content', ''))[:120]}..."
                )

            resumo = "\n\n".join(formatted)
            return f"Ultimas interacoes encontradas:\n\n{resumo}\n\n(Exibindo ate 5 registros.)"

        return f"Retorno inesperado do agente: {type(result)}"

    def _is_current_user_query(self, query: str) -> bool:
        return bool(query and "current_user" in query.lower())

    def _extract_sql_user_token(self, query: str) -> str:
        if not query:
            return ""
        match = re.search(r"user_(-:name|id)\s*=\s*'([^']+)'", query, flags=re.IGNORECASE)
        if not match:
            return ""
        token = match.group(1).strip()
        if token.lower() == "current_user" or not token:
            return ""
        return token

    def _parse_json_result(self, text: str):
        idx = text.find("\n")
        if idx < 0:
            return None
        payload = text[idx + 1 :].strip()
        if not payload:
            return None
        try:
            return json.loads(payload)
        except json.JSONDecodeError:
            return None

    def _format_table(self, rows):
        if not rows:
            return "Nenhuma interacao encontrada."

        ordered_keys = []
        if any(row.get("user_name") for row in rows):
            ordered_keys.append("user_name")
        if any(row.get("user_id") for row in rows):
            ordered_keys.append("user_id")

        seen = set(ordered_keys)
        for row in rows:
            for key in row.keys():
                if key in seen:
                    continue
                seen.add(key)
                ordered_keys.append(key)

        header_names = []
        for key in ordered_keys:
            if key == "user_name":
                header_names.append("Usuario")
            elif key == "user_id":
                header_names.append("User ID")
            else:
                header_names.append(key.replace("_", " ").title())

        lines = [f"| {' | '.join(header_names)} |", "|" + "|".join("---" for _ in header_names) + "|"]
        for row in rows:
            cells = []
            for key in ordered_keys:
                value = row.get(key, "-")
                if isinstance(value, (list, dict)):
                    value = json.dumps(value, ensure_ascii=False)
                if isinstance(value, date):
                    value = value.isoformat()
                cells.append(str(value))
            lines.append(f"| {' | '.join(cells)} |")

        return f"{self.RESULT_PREFIX}\n" + "\n".join(lines)

    def _build_general_query(self) -> str:
        return f"""
            SELECT chat_id, session_id, user_id, user_name, interaction_time,
                   user_question, agent_name, content, module_name
            FROM {self.db.table_name}
            WHERE tenant_id = '{self.db.tenant_id}'
            ORDER BY interaction_time DESC
            LIMIT 5;
        """

    def _build_user_query(self, username: str) -> str:
        safe_username = username.replace("'", "''").strip()
        pattern = f"%{safe_username}%"
        return f"""
            SELECT chat_id, session_id, user_id, user_name, interaction_time,
                   user_question, agent_name, content, module_name
            FROM {self.db.table_name}
            WHERE tenant_id = '{self.db.tenant_id}'
              AND (
                    UPPER(user_name) LIKE UPPER('{pattern}')
                 OR UPPER(user_id) LIKE UPPER('{pattern}')
              )
            ORDER BY interaction_time DESC
            LIMIT 10;
        """

    def _extract_user_name(self, question: str) -> str:
        if not question:
            return ""
        lowered = question.lower()
        match = re.search(r"intera[cç]oes-\s+de\s+([\w\sáéíóúãâêôçÁÉÍÓÚÃÂÊÔÇ]+)", lowered)
        if match:
            name = match.group(1).strip()
            name = re.split(r"\s+do\s+|\s+da\s+|\s+do\s+usuario|\s+de\s+usuario", name)[0]
            return name.strip()
        return ""

    def _ensure_user_names(self, rows):
        missing = {row.get("user_id") for row in rows if row.get("user_id") and not row.get("user_name")}
        if not missing:
            return

        sanitized = ", ".join("'{}'".format(uid.replace("'", "''")) for uid in missing)
        sql = f"""
            SELECT user_id, MAX(user_name) AS user_name
            FROM {self.db.table_name}
            WHERE tenant_id = '{self.db.tenant_id}'
              AND user_id IN ({sanitized})
            GROUP BY user_id;
        """
        lookup = {}
        try:
            name_rows = self.db.query(sql)
            if isinstance(name_rows, list):
                for item in name_rows:
                    if item.get("user_id") and item.get("user_name"):
                        lookup[item["user_id"]] = item["user_name"]
        except Exception:
            return

        for row in rows:
            if not row.get("user_name") and row.get("user_id"):
                row["user_name"] = lookup.get(row["user_id"])

    def _matches_general_request(self, question: str) -> bool:
        return bool(question and any(keyword in question.lower() for keyword in self.GENERAL_KEYWORDS))

    def _query_and_format(self, sql: str) -> str:
        sql = translate_date(sql, self.db.is_local)
        sql = translate_datetime(sql, self.db.is_local)
        sql = translate_time_comparison(sql, self.db.is_local)
        sql = translate_group_concat(sql, self.db.is_local)
        result = execute_with_retries(self.db, sql)
        return self._format_result(result)

    def _audit_logic(self, query: str) -> str:
        if self._is_current_user_query(query):
            return self._query_and_format(self._build_general_query())

        sql_user_token = self._extract_sql_user_token(query)
        if sql_user_token:
            return self._query_and_format(self._build_user_query(sql_user_token))

        user_name = self._extract_user_name(query)
        if user_name:
            return self._query_and_format(self._build_user_query(user_name))

        if self._matches_general_request(query):
            return self._query_and_format(self._build_general_query())

        result = self.agent.execute_audit(query)
        return self._format_result(result)

    def make_tool(self):
        def audit_tool(query: str) -> str:
            return self._audit_logic(query=query)

        return audit_tool
