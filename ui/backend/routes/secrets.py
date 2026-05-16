from fastapi import APIRouter, Depends, Query

from ui.backend.core.db import get_connection, new_id
from ui.backend.core.dependencies import get_current_user, get_secret_or_404, require_permission
from ui.backend.core.schemas import ActiveStatePayload, SecretPayload

router = APIRouter()


def _serialize_secret(row: dict, include_form: bool = False) -> dict:
    item = {
        "id": row["id"],
        "tenant_id": row["tenant_id"],
        "tenant_name": row.get("tenant_name"),
        "name": row["name"],
        "description": row.get("description") or "",
        "secret_value": row.get("secret_value") or "",
        "is_active": row.get("is_active", True),
        "created_at": row["created_at"].isoformat() if row.get("created_at") else None,
        "updated_at": row["updated_at"].isoformat() if row.get("updated_at") else None,
    }
    if include_form:
        item["form"] = {
            "id": row["id"],
            "tenant_id": row["tenant_id"],
            "name": row["name"],
            "description": row.get("description") or "",
            "secret_value": row.get("secret_value") or "",
            "is_active": row.get("is_active", True),
        }
    return item


@router.get("/api/secrets")
def list_secrets(include_inactive: bool = Query(False), current_user: dict = Depends(get_current_user)):
    require_permission(current_user, "secrets", "view")
    if include_inactive:
        require_permission(current_user, "secrets", "view_inactive")

    with get_connection() as conn, conn.cursor() as cur:
        if current_user["role"] == "master":
            cur.execute(
                """
                SELECT s.*, t.name AS tenant_name
                FROM agent_ui_secrets s
                LEFT JOIN agent_ui_tenants t ON t.id = s.tenant_id
                WHERE (%s = TRUE OR s.is_active = TRUE)
                ORDER BY s.updated_at DESC, s.name ASC
                """,
                (include_inactive,),
            )
        else:
            cur.execute(
                """
                SELECT s.*, t.name AS tenant_name
                FROM agent_ui_secrets s
                LEFT JOIN agent_ui_tenants t ON t.id = s.tenant_id
                WHERE s.tenant_id = %s
                  AND (%s = TRUE OR s.is_active = TRUE)
                ORDER BY s.updated_at DESC, s.name ASC
                """,
                (current_user["tenant_id"], include_inactive),
            )
        rows = cur.fetchall()
    return {"items": [_serialize_secret(row) for row in rows]}


@router.get("/api/secrets/{secret_id}")
def get_secret(secret_id: str, current_user: dict = Depends(get_current_user)):
    require_permission(current_user, "secrets", "view")
    row = get_secret_or_404(secret_id, current_user)
    return {"item": _serialize_secret(row, include_form=True)}


@router.post("/api/secrets")
def create_secret(payload: SecretPayload, current_user: dict = Depends(get_current_user)):
    require_permission(current_user, "secrets", "create")
    tenant_id = payload.tenant_id or current_user["tenant_id"]
    if current_user["role"] != "master":
        tenant_id = current_user["tenant_id"]

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO agent_ui_secrets (
                id, tenant_id, name, description, secret_value, is_active, created_by, updated_by
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING *
            """,
            (
                new_id(),
                tenant_id,
                payload.name.strip(),
                payload.description or "",
                payload.secret_value,
                payload.is_active,
                current_user["id"],
                current_user["id"],
            ),
        )
        row = cur.fetchone()
        cur.execute("SELECT name AS tenant_name FROM agent_ui_tenants WHERE id = %s", (tenant_id,))
        tenant_row = cur.fetchone()
        row["tenant_name"] = tenant_row["tenant_name"] if tenant_row else None
    return {"item": _serialize_secret(row, include_form=True)}


@router.put("/api/secrets/{secret_id}")
def update_secret(secret_id: str, payload: SecretPayload, current_user: dict = Depends(get_current_user)):
    require_permission(current_user, "secrets", "edit")
    existing = get_secret_or_404(secret_id, current_user)
    tenant_id = payload.tenant_id or existing["tenant_id"]
    if current_user["role"] != "master":
        tenant_id = existing["tenant_id"]

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            UPDATE agent_ui_secrets
            SET tenant_id = %s,
                name = %s,
                description = %s,
                secret_value = %s,
                is_active = %s,
                updated_by = %s,
                updated_at = NOW()
            WHERE id = %s
            RETURNING *
            """,
            (
                tenant_id,
                payload.name.strip(),
                payload.description or "",
                payload.secret_value,
                payload.is_active,
                current_user["id"],
                secret_id,
            ),
        )
        row = cur.fetchone()
        cur.execute("SELECT name AS tenant_name FROM agent_ui_tenants WHERE id = %s", (tenant_id,))
        tenant_row = cur.fetchone()
        row["tenant_name"] = tenant_row["tenant_name"] if tenant_row else None
    return {"item": _serialize_secret(row, include_form=True)}


@router.put("/api/secrets/{secret_id}/status")
def update_secret_status(secret_id: str, payload: ActiveStatePayload, current_user: dict = Depends(get_current_user)):
    require_permission(current_user, "secrets", "deactivate")
    row = get_secret_or_404(secret_id, current_user)
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            UPDATE agent_ui_secrets
            SET is_active = %s,
                updated_by = %s,
                updated_at = NOW()
            WHERE id = %s
            RETURNING *
            """,
            (payload.is_active, current_user["id"], row["id"]),
        )
        updated = cur.fetchone()
        cur.execute("SELECT name AS tenant_name FROM agent_ui_tenants WHERE id = %s", (updated["tenant_id"],))
        tenant_row = cur.fetchone()
        updated["tenant_name"] = tenant_row["tenant_name"] if tenant_row else None
    return {"item": _serialize_secret(updated, include_form=True)}
