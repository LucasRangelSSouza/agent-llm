#!/usr/bin/env python3
import os
import sqlite3
from pathlib import Path


DB_PATH = Path(os.getenv("RATINGS_DB_PATH", "ratings.db"))


def main() -> None:
    if not DB_PATH.exists():
        print(f"Banco nao encontrado: {DB_PATH}")
        return

    conn = sqlite3.connect(DB_PATH.as_posix())
    try:
        cur = conn.execute(
            """
            SELECT id, message, rate
            FROM ratings
            ORDER BY id DESC
            LIMIT 10
            """
        )
        rows = cur.fetchall()
    finally:
        conn.close()

    if not rows:
        print("Sem registros.")
        return

    for row in rows:
        print(f"id={row[0]} | rate={row[2]} | message={row[1]}")


if __name__ == "__main__":
    main()
