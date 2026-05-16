import os
import re
import sqlite3
import threading
from datetime import datetime

import psycopg2
from psycopg2.extras import DictCursor

import config as settings


class AuditDB:
    def __init__(self, tenant_id: str = "default", db_path=None, is_local=True):
        self.is_local = is_local
        self.tenant_id = self._normalize_tenant_id(tenant_id)
        self.table_name = settings.AGENT_INTERACTIONS_TABLE
        self._lock = threading.Lock()

        if is_local:
            base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../.."))
            if db_path and os.path.isdir(db_path):
                db_path = os.path.join(db_path, "audit.db")
            elif not db_path:
                db_path = os.path.join(base_dir, "audit.db")
            self.db_path = os.path.normpath(db_path.strip())
        else:
            self.rds_config = {
                "host": settings.RDS_HOST,
                "port": settings.RDS_PORT,
                "dbname": settings.RDS_DB,
                "user": settings.RDS_USER,
                "password": settings.RDS_PASSWORD,
            }

        self._init_db()

    def _normalize_tenant_id(self, raw: str) -> str:
        value = (raw or "").strip().strip("/")
        value = value.replace("-", "_")
        value = re.sub(r"[^0-9a-zA-Z_]+", "_", value)
        return value or "default"

    def _get_conn(self):
        if self.is_local:
            conn = sqlite3.connect(self.db_path, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            return conn
        return psycopg2.connect(**self.rds_config, cursor_factory=DictCursor)

    def _init_db(self):
        if self.is_local:
            with self._get_conn() as conn:
                conn.execute(
                    f"""
                    CREATE TABLE IF NOT EXISTS {self.table_name} (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        tenant_id TEXT NOT NULL,
                        chat_id TEXT,
                        session_id TEXT,
                        user_id TEXT,
                        user_name TEXT,
                        interaction_time TEXT NOT NULL,
                        user_question TEXT,
                        agent_name TEXT,
                        content TEXT,
                        module_name TEXT,
                        feedback TEXT,
                        source TEXT NOT NULL DEFAULT 'ai_runtime',
                        legacy_table TEXT,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    )
                    """
                )
        else:
            with self._get_conn() as conn, conn.cursor() as cur:
                cur.execute(
                    f"""
                    CREATE TABLE IF NOT EXISTS {self.table_name} (
                        id BIGSERIAL PRIMARY KEY,
                        tenant_id TEXT NOT NULL,
                        chat_id TEXT,
                        session_id TEXT,
                        user_id TEXT,
                        user_name TEXT,
                        interaction_time TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        user_question TEXT,
                        agent_name TEXT,
                        content TEXT,
                        module_name TEXT,
                        feedback TEXT,
                        source TEXT NOT NULL DEFAULT 'ai_runtime',
                        legacy_table TEXT,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    );
                    """
                )
                cur.execute(
                    f"""
                    CREATE UNIQUE INDEX IF NOT EXISTS uq_{self.table_name}_runtime
                    ON {self.table_name} (
                        tenant_id,
                        session_id,
                        interaction_time,
                        COALESCE(agent_name, '')
                    );
                    """
                )
                cur.execute(
                    f"""
                    CREATE INDEX IF NOT EXISTS idx_{self.table_name}_tenant_time
                    ON {self.table_name} (tenant_id, interaction_time DESC);
                    """
                )
                conn.commit()

    def _sql_literal(self, value: str) -> str:
        return "'" + str(value or "").replace("'", "''") + "'"

    def _apply_tenant_scope(self, sql: str) -> str:
        if self.is_local or not self.tenant_id:
            return sql

        cleaned = (sql or "").strip().rstrip(";")
        lowered = cleaned.lower()
        if self.table_name.lower() not in lowered:
            return cleaned
        if "tenant_id" in lowered:
            return cleaned

        tenant_filter = f"tenant_id = {self._sql_literal(self.tenant_id)}"

        where_match = re.search(r"\bwhere\b", cleaned, flags=re.IGNORECASE)
        if where_match:
            return re.sub(
                r"\bwhere\b",
                f"WHERE {tenant_filter} AND ",
                cleaned,
                count=1,
                flags=re.IGNORECASE,
            )

        split_match = re.search(
            r"\b(group\s+by|order\s+by|limit|offset)\b",
            cleaned,
            flags=re.IGNORECASE,
        )
        if split_match:
            idx = split_match.start()
            return f"{cleaned[:idx]} WHERE {tenant_filter} {cleaned[idx:]}"

        return f"{cleaned} WHERE {tenant_filter}"

    def insert_interaction(
        self,
        *,
        tenant_id: str,
        chat_id: str | None,
        session_id: str | None,
        user_id: str | None,
        user_name: str | None,
        interaction_time: str | datetime | None,
        user_question: str | None,
        agent_name: str | None,
        content: str | None,
        module_name: str | None,
        feedback: str | None = None,
        source: str = "ai_runtime",
        legacy_table: str | None = None,
    ) -> None:
        tenant_value = self._normalize_tenant_id(tenant_id or self.tenant_id)
        now = datetime.utcnow().isoformat()

        if isinstance(interaction_time, datetime):
            interaction_value = interaction_time.isoformat()
        else:
            interaction_value = str(interaction_time or now)

        payload = (
            tenant_value,
            chat_id,
            session_id,
            user_id,
            user_name,
            interaction_value,
            user_question,
            agent_name,
            content,
            module_name,
            feedback,
            source,
            legacy_table,
            now,
            now,
        )

        with self._lock, self._get_conn() as conn:
            if self.is_local:
                conn.execute(
                    f"""
                    INSERT INTO {self.table_name} (
                        tenant_id,
                        chat_id,
                        session_id,
                        user_id,
                        user_name,
                        interaction_time,
                        user_question,
                        agent_name,
                        content,
                        module_name,
                        feedback,
                        source,
                        legacy_table,
                        created_at,
                        updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    payload,
                )
                conn.commit()
            else:
                with conn.cursor() as cur:
                    cur.execute(
                        f"""
                        INSERT INTO {self.table_name} (
                            tenant_id,
                            chat_id,
                            session_id,
                            user_id,
                            user_name,
                            interaction_time,
                            user_question,
                            agent_name,
                            content,
                            module_name,
                            feedback,
                            source,
                            legacy_table,
                            created_at,
                            updated_at
                        ) VALUES (%s, %s, %s, %s, %s, %s::timestamptz, %s, %s, %s, %s, %s, %s, %s, %s::timestamptz, %s::timestamptz)
                        ON CONFLICT DO NOTHING
                        """,
                        payload,
                    )
                conn.commit()

    def query(self, sql: str):
        scoped_sql = self._apply_tenant_scope(sql)
        try:
            with self._lock, self._get_conn() as conn:
                if self.is_local:
                    rows = conn.execute(scoped_sql).fetchall()
                else:
                    with conn.cursor() as cur:
                        cur.execute(scoped_sql)
                        rows = cur.fetchall()
            return [dict(row) for row in rows] if rows else "Nenhum dado encontrado."
        except Exception as error:
            return f"Erro: {error}"

    def fetch_recent_chat_interactions(self, chat_id: str | None, limit: int = 6):
        if not chat_id:
            return []

        safe_limit = max(1, min(int(limit or 6), 20))

        with self._lock, self._get_conn() as conn:
            if self.is_local:
                rows = conn.execute(
                    f"""
                    SELECT user_question, content, agent_name, module_name, interaction_time
                    FROM {self.table_name}
                    WHERE tenant_id = ? AND chat_id = ?
                    ORDER BY interaction_time DESC, id DESC
                    LIMIT ?
                    """,
                    (self.tenant_id, chat_id, safe_limit),
                ).fetchall()
            else:
                with conn.cursor() as cur:
                    cur.execute(
                        f"""
                        SELECT user_question, content, agent_name, module_name, interaction_time
                        FROM {self.table_name}
                        WHERE tenant_id = %s AND chat_id = %s
                        ORDER BY interaction_time DESC, id DESC
                        LIMIT %s
                        """,
                        (self.tenant_id, chat_id, safe_limit),
                    )
                    rows = cur.fetchall()

        return list(reversed(rows))
