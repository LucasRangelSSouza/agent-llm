import uuid
from contextlib import contextmanager

import psycopg2
from psycopg2.extras import RealDictCursor

from ui.backend.core import config


def new_id() -> str:
    return uuid.uuid4().hex


@contextmanager
def get_connection():
    conn = psycopg2.connect(
        host=config.UI_DB_HOST,
        port=config.UI_DB_PORT,
        dbname=config.UI_DB_NAME,
        user=config.UI_DB_USER,
        password=config.UI_DB_PASSWORD,
        cursor_factory=RealDictCursor,
    )
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
