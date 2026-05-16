import json
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import Header, HTTPException

from ui.backend.core import config
from ui.backend.core.db import get_connection, new_id


PERMISSION_RESOURCES = [
    "templates",
    "ai_services",
    "datasources",
    "files",
    "secrets",
    "users",
    "preferences",
    "user_profiles",
]
PERMISSION_ACTIONS = ["view", "edit", "create", "view_inactive", "deactivate"]


def full_permissions() -> dict:
    return {
        resource: {action: True for action in PERMISSION_ACTIONS}
        for resource in PERMISSION_RESOURCES
    }


def default_user_permissions() -> dict:
    permissions = {
        resource: {action: False for action in PERMISSION_ACTIONS}
        for resource in PERMISSION_RESOURCES
    }
    permissions["preferences"]["view"] = True
    permissions["preferences"]["edit"] = True
    return permissions


def normalize_permissions(value) -> dict:
    if isinstance(value, str):
        value = safe_json_loads(value) or {}
    if not isinstance(value, dict):
        value = {}
    permissions = default_user_permissions()
    for resource in PERMISSION_RESOURCES:
        raw_resource = value.get(resource) or {}
        if isinstance(raw_resource, dict):
            for action in PERMISSION_ACTIONS:
                permissions[resource][action] = bool(raw_resource.get(action, permissions[resource][action]))
    return permissions


def safe_json_loads(text: str):
    try:
        return json.loads(text)
    except Exception:
        return None


def parse_sse_text_payload(text: str) -> str:
    if not text:
        return ""

    chunks = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line.startswith("data:"):
            continue
        payload = line[5:].strip()
        if payload in {"ok", "done", ""}:
            continue
        parsed = safe_json_loads(payload)
        if isinstance(parsed, str):
            chunks.append(parsed)
        elif parsed is not None:
            chunks.append(json.dumps(parsed, ensure_ascii=False))
        else:
            chunks.append(payload)

    return "".join(chunks).strip()


def serialize_user(row: dict) -> dict:
    permissions = full_permissions() if row.get("role") == "master" else normalize_permissions(row.get("profile_permissions"))
    return {
        "id": row["id"],
        "tenant_id": row["tenant_id"],
        "tenant_key": row.get("tenant_key"),
        "full_name": row["full_name"],
        "email": row["email"],
        "phone": row.get("phone"),
        "about": row.get("about"),
        "role": row.get("role"),
        "profile_id": row.get("profile_id"),
        "profile_name": row.get("profile_name"),
        "permissions": permissions,
        "is_active": row.get("is_active"),
        "created_at": row.get("created_at").isoformat() if row.get("created_at") else None,
    }


def serialize_tenant(row: dict) -> dict:
    return {
        "id": row["id"],
        "name": row["name"],
        "cnpj": row["cnpj"],
        "legal_name": row["legal_name"],
        "tenant_key": row.get("tenant_key"),
        "is_active": row.get("is_active", True),
        "created_at": row["created_at"].isoformat() if row["created_at"] else None,
    }


def create_session(user_id: str, session_hours: int) -> str:
    token = uuid.uuid4().hex
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(hours=session_hours)
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO agent_ui_sessions (id, user_id, token, expires_at, last_activity_at)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (new_id(), user_id, token, expires_at, now),
        )
    return token


def get_current_user(authorization: str = Header(default="")) -> dict:
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Sessao invalida")

    token = authorization.replace("Bearer ", "", 1).strip()
    idle_cutoff = datetime.now(timezone.utc) - timedelta(minutes=config.UI_SESSION_IDLE_MINUTES)

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                s.token,
                s.expires_at,
                s.last_activity_at,
                u.id,
                u.tenant_id,
                t.tenant_key,
                u.full_name,
                u.email,
                u.phone,
                u.about,
                u.role,
                u.profile_id,
                p.name AS profile_name,
                p.permissions AS profile_permissions,
                u.is_active
            FROM agent_ui_sessions s
            JOIN agent_ui_users u ON u.id = s.user_id
            LEFT JOIN agent_ui_tenants t ON t.id = u.tenant_id
            LEFT JOIN agent_ui_user_profiles p ON p.id = u.profile_id
            WHERE s.token = %s
              AND s.revoked_at IS NULL
              AND s.expires_at > NOW()
              AND COALESCE(s.last_activity_at, s.created_at) > %s
              AND u.is_active = TRUE
            LIMIT 1
            """,
            (token, idle_cutoff),
        )
        row = cur.fetchone()

        if row:
            cur.execute(
                """
                UPDATE agent_ui_sessions
                SET last_activity_at = NOW()
                WHERE token = %s
                """,
                (token,),
            )
        else:
            cur.execute(
                """
                UPDATE agent_ui_sessions
                SET revoked_at = COALESCE(revoked_at, NOW())
                WHERE token = %s
                  AND revoked_at IS NULL
                  AND (expires_at <= NOW() OR COALESCE(last_activity_at, created_at) <= %s)
                """,
                (token, idle_cutoff),
            )

    if not row:
        raise HTTPException(status_code=401, detail="Sessao expirada")

    row["session_token"] = row["token"]
    return row


def require_master(current_user: dict) -> None:
    if current_user["role"] != "master":
        raise HTTPException(status_code=403, detail="Acesso restrito ao perfil master")


def has_permission(current_user: dict, resource: str, action: str = "view") -> bool:
    if current_user.get("role") == "master":
        return True
    permissions = normalize_permissions(current_user.get("profile_permissions") or current_user.get("permissions"))
    return bool(permissions.get(resource, {}).get(action))


def require_permission(current_user: dict, resource: str, action: str = "view") -> None:
    if not has_permission(current_user, resource, action):
        raise HTTPException(status_code=403, detail="Usuario sem permissao nesse recurso")


def get_datasource_or_404(datasource_id: str, current_user: dict) -> dict:
    with get_connection() as conn, conn.cursor() as cur:
        if current_user["role"] == "master":
            cur.execute(
                """
                SELECT d.*, t.name AS tenant_name
                FROM agent_ui_datasources d
                LEFT JOIN agent_ui_tenants t ON t.id = d.tenant_id
                WHERE d.id = %s
                LIMIT 1
                """,
                (datasource_id,),
            )
        else:
            cur.execute(
                """
                SELECT d.*, t.name AS tenant_name
                FROM agent_ui_datasources d
                LEFT JOIN agent_ui_tenants t ON t.id = d.tenant_id
                WHERE d.id = %s
                  AND d.tenant_id = %s
                LIMIT 1
                """,
                (datasource_id, current_user["tenant_id"]),
            )
        row = cur.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Datasource nao encontrado")
    return row


def get_ai_service_or_404(ai_service_id: str, current_user: dict) -> dict:
    with get_connection() as conn, conn.cursor() as cur:
        if current_user["role"] == "master":
            cur.execute(
                """
                SELECT s.*, t.name AS tenant_name
                FROM agent_ui_ai_services s
                LEFT JOIN agent_ui_tenants t ON t.id = s.tenant_id
                WHERE s.id = %s
                LIMIT 1
                """,
                (ai_service_id,),
            )
        else:
            cur.execute(
                """
                SELECT s.*, t.name AS tenant_name
                FROM agent_ui_ai_services s
                LEFT JOIN agent_ui_tenants t ON t.id = s.tenant_id
                WHERE s.id = %s
                  AND s.tenant_id = %s
                LIMIT 1
                """,
                (ai_service_id, current_user["tenant_id"]),
            )
        row = cur.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Servico de IA nao encontrado")
    return row


def get_file_or_404(file_id: str, current_user: dict) -> dict:
    with get_connection() as conn, conn.cursor() as cur:
        if current_user["role"] == "master":
            cur.execute(
                """
                SELECT f.*, t.name AS tenant_name
                FROM agent_ui_files f
                LEFT JOIN agent_ui_tenants t ON t.id = f.tenant_id
                WHERE f.id = %s
                LIMIT 1
                """,
                (file_id,),
            )
        else:
            cur.execute(
                """
                SELECT f.*, t.name AS tenant_name
                FROM agent_ui_files f
                LEFT JOIN agent_ui_tenants t ON t.id = f.tenant_id
                WHERE f.id = %s
                  AND f.tenant_id = %s
                LIMIT 1
                """,
                (file_id, current_user["tenant_id"]),
            )
        row = cur.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Arquivo nao encontrado")
    return row


def get_secret_or_404(secret_id: str, current_user: dict) -> dict:
    with get_connection() as conn, conn.cursor() as cur:
        if current_user["role"] == "master":
            cur.execute(
                """
                SELECT s.*, t.name AS tenant_name
                FROM agent_ui_secrets s
                LEFT JOIN agent_ui_tenants t ON t.id = s.tenant_id
                WHERE s.id = %s
                LIMIT 1
                """,
                (secret_id,),
            )
        else:
            cur.execute(
                """
                SELECT s.*, t.name AS tenant_name
                FROM agent_ui_secrets s
                LEFT JOIN agent_ui_tenants t ON t.id = s.tenant_id
                WHERE s.id = %s
                  AND s.tenant_id = %s
                LIMIT 1
                """,
                (secret_id, current_user["tenant_id"]),
            )
        row = cur.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Secret nao encontrado")
    return row
