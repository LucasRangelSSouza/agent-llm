from pathlib import Path

from ui.backend.core import config
from ui.backend.core.db import get_connection
from ui.backend.core.security import hash_password
from ui.backend.core.db import new_id
from ui.backend.domains.templates import bootstrap_legacy_templates, ensure_tenant_keys
from psycopg2.extras import Json


ADMIN_PERMISSIONS = {
    resource: {action: True for action in ["view", "edit", "create", "view_inactive", "deactivate"]}
    for resource in ["templates", "ai_services", "datasources", "files", "secrets", "users", "preferences", "user_profiles"]
}


USER_PERMISSIONS = {
    "templates": {"view": False, "edit": False, "create": False, "view_inactive": False, "deactivate": False},
    "ai_services": {"view": False, "edit": False, "create": False, "view_inactive": False, "deactivate": False},
    "datasources": {"view": False, "edit": False, "create": False, "view_inactive": False, "deactivate": False},
    "files": {"view": False, "edit": False, "create": False, "view_inactive": False, "deactivate": False},
    "secrets": {"view": False, "edit": False, "create": False, "view_inactive": False, "deactivate": False},
    "users": {"view": False, "edit": False, "create": False, "view_inactive": False, "deactivate": False},
    "preferences": {"view": True, "edit": True, "create": False, "view_inactive": False, "deactivate": False},
    "user_profiles": {"view": False, "edit": False, "create": False, "view_inactive": False, "deactivate": False},
}


def ensure_default_profiles(cur, tenant_id: str) -> None:
    cur.execute(
        """
        INSERT INTO agent_ui_user_profiles (id, tenant_id, name, permissions, is_active)
        VALUES (%s, %s, 'Admin', %s, TRUE)
        ON CONFLICT (id) DO NOTHING
        """,
        (f"profile_admin_{tenant_id}", tenant_id, Json(ADMIN_PERMISSIONS)),
    )
    cur.execute(
        """
        INSERT INTO agent_ui_user_profiles (id, tenant_id, name, permissions, is_active)
        VALUES (%s, %s, 'Usuario', %s, TRUE)
        ON CONFLICT (id) DO NOTHING
        """,
        (f"profile_user_{tenant_id}", tenant_id, Json(USER_PERMISSIONS)),
    )


def _migration_files():
    return sorted(Path(config.MIGRATIONS_DIR).glob("*.sql"))


def run_migrations() -> None:
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS agent_ui_schema_migrations (
                version TEXT PRIMARY KEY,
                applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )
        cur.execute("SELECT version FROM agent_ui_schema_migrations")
        applied = {row["version"] for row in cur.fetchall()}

        for migration_file in _migration_files():
            version = migration_file.name
            if version in applied:
                continue
            sql = migration_file.read_text(encoding="utf-8")
            cur.execute(sql)
            cur.execute(
                "INSERT INTO agent_ui_schema_migrations (version) VALUES (%s)",
                (version,),
            )


def bootstrap_master_user() -> None:
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT id
            FROM agent_ui_users
            WHERE role = 'master'
            LIMIT 1
            """
        )
        if cur.fetchone():
            ensure_tenant_keys()
            bootstrap_legacy_templates()
            return

        tenant_id = new_id()
        user_id = new_id()
        cur.execute(
            """
            INSERT INTO agent_ui_tenants (id, name, cnpj, legal_name)
            VALUES (%s, %s, %s, %s)
            """,
            (
                tenant_id,
                config.UI_MASTER_TENANT_NAME,
                config.UI_MASTER_TENANT_CNPJ,
                config.UI_MASTER_TENANT_LEGAL_NAME,
            ),
        )
        cur.execute(
            """
            INSERT INTO agent_ui_users (
                id,
                tenant_id,
                full_name,
                email,
                phone,
                about,
                role,
                profile_id,
                password_hash,
                is_active
            )
            VALUES (%s, %s, %s, %s, %s, %s, 'master', 'profile_master_global', %s, TRUE)
            """,
            (
                user_id,
                tenant_id,
                config.UI_MASTER_NAME,
                config.UI_MASTER_EMAIL,
                config.UI_MASTER_PHONE,
                config.UI_MASTER_ABOUT,
                hash_password(config.UI_MASTER_PASSWORD),
            ),
        )
        ensure_default_profiles(cur, tenant_id)
    ensure_tenant_keys()
    bootstrap_legacy_templates()
