import sqlite3
import json
import psycopg2
from psycopg2.extras import DictCursor
import config as settings
from datetime import datetime
from zoneinfo import ZoneInfo


class FrontDB:
    def __init__(self, use_local: bool = True, read_only: bool = False):
        self.use_local = use_local
        self.read_only = read_only
        if not self.read_only:
            self._init_db()

    def _get_conn(self):
        if self.use_local:
            return sqlite3.connect(settings.LOCAL_FRONT_DB_PATH)
        return psycopg2.connect(
            host=settings.RDS_FRONT_HOST,
            port=settings.RDS_FRONT_PORT,
            dbname=settings.RDS_FRONT_DB,
            user=settings.RDS_FRONT_USER,
            password=settings.RDS_FRONT_PASSWORD,
            cursor_factory=DictCursor,
        )

    def _init_db(self):
        if self.use_local:
            conn = self._get_conn()
            try:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS Message (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        chat_id TEXT,
                        content TEXT,
                        role TEXT,
                        created_at TEXT NOT NULL,
                        feedback TEXT NULL
                    );
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS MessageFeedbackSeen (
                        chat_id TEXT,
                        message_id INTEGER,
                        feedback TEXT,
                        seen_at TEXT NOT NULL,
                        PRIMARY KEY (chat_id, message_id)
                    );
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS MessageFeedbackSummary (
                        chat_id TEXT PRIMARY KEY,
                        ids_json TEXT NOT NULL,
                        summary_json TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    );
                    """
                )
                conn.commit()
            finally:
                conn.close()
        else:
            with self._get_conn() as conn, conn.cursor() as cur:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS public."Message" (
                        id SERIAL PRIMARY KEY,
                        chat_id TEXT,
                        content TEXT,
                        role TEXT,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        feedback TEXT NULL
                    );
                    """
                )
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS public."MessageFeedbackSeen" (
                        chat_id TEXT,
                        message_id INTEGER,
                        feedback TEXT,
                        seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        PRIMARY KEY (chat_id, message_id)
                    );
                    """
                )
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS public."MessageFeedbackSummary" (
                        chat_id TEXT PRIMARY KEY,
                        ids_json TEXT NOT NULL,
                        summary_json TEXT NOT NULL,
                        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    );
                    """
                )
                conn.commit()

    def insert_messages(self, rows):
        if not rows:
            return
        if self.read_only:
            return
        if self.use_local:
            conn = self._get_conn()
            try:
                conn.executemany(
                    """
                    INSERT INTO Message (
                        chat_id, content, role, created_at, feedback
                    ) VALUES (?, ?, ?, ?, ?);
                    """,
                    rows,
                )
                conn.commit()
            finally:
                conn.close()
        else:
            with self._get_conn() as conn, conn.cursor() as cur:
                cur.executemany(
                    """
                    INSERT INTO public."Message" (
                        chat_id, content, role, created_at, feedback
                    ) VALUES (%s, %s, %s, %s, %s);
                    """,
                    rows,
                )
                conn.commit()

    def _get_summary_state(self, chat_id: str):
        if self.use_local:
            conn = self._get_conn()
            try:
                cur = conn.cursor()
                cur.execute(
                    "SELECT ids_json, summary_json FROM MessageFeedbackSummary WHERE chat_id = ?",
                    (chat_id,),
                )
                row = cur.fetchone()
            finally:
                conn.close()
        else:
            with self._get_conn() as conn, conn.cursor() as cur:
                cur.execute(
                    'SELECT ids_json, summary_json FROM public."MessageFeedbackSummary" WHERE chat_id = %s',
                    (chat_id,),
                )
                row = cur.fetchone()

        if not row:
            return [], {"manter": [], "melhorar": [], "evitar": []}

        try:
            ids = json.loads(row[0]) if row[0] else []
        except Exception:
            ids = []
        try:
            summary = json.loads(row[1]) if row[1] else {"manter": [], "melhorar": [], "evitar": []}
        except Exception:
            summary = {"manter": [], "melhorar": [], "evitar": []}

        return ids, summary

    def _save_summary_state(self, chat_id: str, ids, summary):
        if self.read_only:
            return
        now = datetime.now(ZoneInfo("America/Sao_Paulo")).isoformat()
        ids_json = json.dumps(sorted(set(ids)))
        summary_json = json.dumps(summary, ensure_ascii=False)

        if self.use_local:
            conn = self._get_conn()
            try:
                conn.execute(
                    """
                    INSERT INTO MessageFeedbackSummary (chat_id, ids_json, summary_json, updated_at)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(chat_id) DO UPDATE SET
                        ids_json=excluded.ids_json,
                        summary_json=excluded.summary_json,
                        updated_at=excluded.updated_at;
                    """,
                    (chat_id, ids_json, summary_json, now),
                )
                conn.commit()
            finally:
                conn.close()
        else:
            with self._get_conn() as conn, conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO public."MessageFeedbackSummary" (chat_id, ids_json, summary_json, updated_at)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (chat_id) DO UPDATE SET
                        ids_json=EXCLUDED.ids_json,
                        summary_json=EXCLUDED.summary_json,
                        updated_at=EXCLUDED.updated_at;
                    """,
                    (chat_id, ids_json, summary_json, now),
                )
                conn.commit()

    def build_feedback_context(self, chat_id: str):
        if not chat_id:
            return None

        if self.use_local:
            conn = self._get_conn()
            try:
                cur = conn.cursor()
                cur.execute(
                    """
                    SELECT id, role, content, feedback
                    FROM Message
                    WHERE chat_id = ?
                    ORDER BY id ASC;
                    """,
                    (chat_id,),
                )
                rows = cur.fetchall()
            finally:
                conn.close()
        else:
            with self._get_conn() as conn, conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, user_question, content, feedback
                    FROM public.agent_interactions
                    WHERE chat_id = %s
                    ORDER BY interaction_time ASC, id ASC;
                    """,
                    (chat_id,),
                )
                rows = cur.fetchall()

        if not rows:
            return None

        # Read-only: apenas consulta e retorna ids/feedbacks, sem persistir
        if self.read_only:
            feedback_items = []
            for row in rows:
                msg_id = row[0]
                question = row[1] or ""
                content = row[2] or ""
                feedback = row[3]
                if feedback:
                    feedback_items.append(
                        {
                            "id": msg_id,
                            "question": question,
                            "answer": content,
                            "feedback": feedback,
                        }
                    )
            if not feedback_items:
                return None
            lines = [
                "Preferencias internas do usuario (nao responder com isso):",
                "Baseado em feedbacks anteriores:",
            ]
            for it in feedback_items:
                q = it["question"].replace("\n", " ").strip()
                a = it["answer"].replace("\n", " ").strip()
                lines.append(f"- id {it['id']} | {q} | {a} - {it['feedback']}")
            return "\n".join(lines)

        seen_ids, summary_state = self._get_summary_state(chat_id)
        last_user = None
        feedback_items = []

        for row in rows:
            msg_id = row[0]
            role = row[1]
            content = row[2] or ""
            feedback = row[3]

            if role == "user":
                last_user = content
                continue

            if role == "assistant" and feedback:
                if msg_id in seen_ids:
                    continue
                feedback_items.append(
                    {
                        "id": msg_id,
                        "question": last_user or "",
                        "answer": content,
                        "feedback": feedback,
                    }
                )

        if not feedback_items:
            return None

        for it in feedback_items:
            print(
                "✅ Feedback recebido: resposta '"
                + (it["answer"][:200].replace("\n", " ") + ("..." if len(it["answer"]) > 200 else ""))
                + "' feedback "
                + it["feedback"]
                + " alimentando base de preferencias do usuario"
            )
        # Atualiza resumo persistido com novos feedbacks
        new_ids = list(seen_ids)
        for it in feedback_items:
            new_ids.append(it["id"])
            line = f"{it['question']} | {it['answer']}".strip()
            if it["feedback"] == "like":
                summary_state["manter"].append(line)
            else:
                summary_state["melhorar"].append(line)
                summary_state["evitar"].append(line)

        self._save_summary_state(chat_id, new_ids, summary_state)

        lines = [
            "Preferencias internas do usuario (nao responder com isso):",
            "Resumo atual (nao repetir como texto literal ao usuario):",
            "Manter:",
        ]
        for item in summary_state["manter"]:
            lines.append(f"- {item}")
        lines.append("Melhorar:")
        for item in summary_state["melhorar"]:
            lines.append(f"- {item}")
        lines.append("Evitar:")
        for item in summary_state["evitar"]:
            lines.append(f"- {item}")

        return "\n".join(lines)
