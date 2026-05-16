import json
import logging
import re

from agent.modules.db.audit_db import AuditDB
from agent.infrastructure.runtime.ai_service import generate_text_reply

logger = logging.getLogger(__name__)


class AuditQueryAgent:
    """Executa consultas SQL sobre o log unificado de interações."""

    def __init__(self, db: AuditDB, model="gpt-4o-mini", ai_service=None):
        self.db = db
        self.model = model
        self.ai_service = ai_service

    def _clean_sql(self, text: str) -> str:
        text = text.strip()
        text = re.sub(r"^```sql", "", text, flags=re.IGNORECASE)
        text = re.sub(r"^```", "", text)
        text = re.sub(r"```$", "", text)
        return text.strip()

    def interpret_query(self, question: str) -> str:
        dialect = "SQLite" if self.db.is_local else "PostgreSQL"
        prompt = f"""
Voce e um assistente que converte perguntas humanas em consultas SQL ({dialect}).

A tabela se chama `{self.db.table_name}` e possui as seguintes colunas:
- tenant_id
- chat_id
- session_id
- user_id
- user_name
- interaction_time
- user_question
- agent_name
- content
- module_name
- feedback
- source

Regras obrigatorias:
- Sempre consulte a tabela `{self.db.table_name}`.
- Sempre filtre `tenant_id = '{self.db.tenant_id}'`.
- Quando o usuario perguntar sobre interacoes, acessos ou quantidades, inclua `user_name` e `user_id` no SELECT quando fizer sentido.
- Trate `interaction_time` como `timestamptz` no PostgreSQL.
- Responda SOMENTE com a query SQL completa e valida.
- Nao use markdown.

Pergunta:
{question}
"""
        try:
            sql = generate_text_reply(
                name="audit_sql_interpreter",
                system_message="Converta perguntas humanas em SQL válido sem explicações extras.",
                user_message=prompt,
                ai_service=self.ai_service,
                model_override=self.model,
            ).strip()
            return self._clean_sql(sql)
        except Exception as error:
            logger.error(f"Erro ao interpretar query de auditoria: {error}")
            return ""

    def execute_audit(self, question: str) -> str:
        sql = self.interpret_query(question)
        if not sql:
            return "Nao consegui interpretar a consulta."

        result = self.db.query(sql)
        if isinstance(result, str):
            return result
        if not result:
            return "Nenhum resultado encontrado."

        try:
            formatted = json.dumps(result, indent=2, ensure_ascii=False)
            return f"Resultado encontrado:\n{formatted}"
        except Exception as error:
            return f"Erro ao formatar resultado: {error}"
