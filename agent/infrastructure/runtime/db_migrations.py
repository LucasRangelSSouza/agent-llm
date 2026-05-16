from pathlib import Path

import psycopg2

import config as settings


def _migration_files():
    base_dir = Path(__file__).resolve().parents[3]
    return sorted((base_dir / "db" / "migrations").glob("*.sql"))


def run_db_migrations() -> None:
    conn = psycopg2.connect(
        host=settings.RDS_HOST,
        port=settings.RDS_PORT,
        dbname=settings.RDS_DB,
        user=settings.RDS_USER,
        password=settings.RDS_PASSWORD,
    )
    try:
        with conn, conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS agent_schema_migrations (
                    version TEXT PRIMARY KEY,
                    applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
            cur.execute("SELECT version FROM agent_schema_migrations")
            applied = {row[0] for row in cur.fetchall()}

            for migration_file in _migration_files():
                version = migration_file.name
                if version in applied:
                    continue
                sql = migration_file.read_text(encoding="utf-8")
                cur.execute(sql)
                cur.execute(
                    "INSERT INTO agent_schema_migrations (version) VALUES (%s)",
                    (version,),
                )
    finally:
        conn.close()
