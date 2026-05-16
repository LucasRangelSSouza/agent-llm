import os
import sqlite3
from pathlib import Path
from typing import Optional

from agent.memory.auto_memory import normalize_rating


DB_PATH = Path(os.getenv("RATINGS_DB_PATH", "ratings.db"))


def _connect() -> sqlite3.Connection:
    return sqlite3.connect(DB_PATH.as_posix())


def ensure_db() -> None:
    conn = _connect()
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS ratings (
                id INTEGER PRIMARY KEY,
                message TEXT,
                rate TEXT
            )
            """
        )
        conn.commit()
    finally:
        conn.close()


def get_rate_by_message_id(message_id: Optional[str]) -> Optional[str]:
    if not message_id:
        return None
    ensure_db()
    conn = _connect()
    try:
        cur = conn.execute("SELECT rate FROM ratings WHERE id = ? LIMIT 1", (message_id,))
        row = cur.fetchone()
        if not row:
            return None
        rate = row[0]
        return normalize_rating(rate)
    finally:
        conn.close()
