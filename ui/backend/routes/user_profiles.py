from fastapi import APIRouter, Depends, HTTPException, Query
from psycopg2.extras import Json

from ui.backend.core.db import get_connection, new_id
from ui.backend.core.dependencies import get_current_user, normalize_permissions, require_permission
from ui.backend.core.schemas import ActiveStatePayload, UserProfilePayload

router = APIRouter()


def serialize_profile(row: dict) -> dict:
    return {
        "id": row["id"],
        "tenant_id": row.get("tenant_id"),
        "tenant_name": row.get("tenant_name"),
        "name": row["name"],
        "permissions": normalize_permissions(row.get("permissions")),
        "is_active": row.get("is_active", True),
        "created_at": row.get("created_at").isoformat() if row.get("created_at") else None,
    }


@router.get("/api/user-profiles")
def list_user_profiles(include_inactive: bool = Query(False), current_user: dict = Depends(get_current_user)):
    require_permission(current_user, "user_profiles", "view")
    if include_inactive:
        require_permission(current_user, "user_profiles", "view_inactive")

    with get_connection() as conn, conn.cursor() as cur:
        if current_user["role"] == "master":
            cur.execute(
                """
                SELECT p.*, t.name AS tenant_name
                FROM agent_ui_user_profiles p
                LEFT JOIN agent_ui_tenants t ON t.id = p.tenant_id
                WHERE (%s = TRUE OR p.is_active = TRUE)
                ORDER BY t.name NULLS FIRST, p.name ASC
                """,
                (include_inactive,),
            )
        else:
            cur.execute(
                """
                SELECT p.*, t.name AS tenant_name
                FROM agent_ui_user_profiles p
                LEFT JOIN agent_ui_tenants t ON t.id = p.tenant_id
                WHERE p.tenant_id = %s
                  AND (%s = TRUE OR p.is_active = TRUE)
                ORDER BY p.name ASC
                """,
                (current_user["tenant_id"], include_inactive),
            )
        rows = cur.fetchall()
    return {"items": [serialize_profile(row) for row in rows]}


@router.post("/api/user-profiles")
def create_user_profile(payload: UserProfilePayload, current_user: dict = Depends(get_current_user)):
    require_permission(current_user, "user_profiles", "create")
    tenant_id = payload.tenant_id or current_user["tenant_id"]
    if current_user["role"] != "master":
        tenant_id = current_user["tenant_id"]

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO agent_ui_user_profiles (id, tenant_id, name, permissions, is_active)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING *
            """,
            (new_id(), tenant_id, payload.name, Json(normalize_permissions(payload.permissions)), payload.is_active),
        )
        row = cur.fetchone()
    return {"item": serialize_profile(row)}


@router.put("/api/user-profiles/{profile_id}")
def update_user_profile(profile_id: str, payload: UserProfilePayload, current_user: dict = Depends(get_current_user)):
    require_permission(current_user, "user_profiles", "edit")
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT * FROM agent_ui_user_profiles WHERE id = %s LIMIT 1", (profile_id,))
        existing = cur.fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail="Perfil nao encontrado")
        if current_user["role"] != "master" and existing["tenant_id"] != current_user["tenant_id"]:
            raise HTTPException(status_code=403, detail="Usuario sem permissao nesse recurso")

        tenant_id = payload.tenant_id or existing["tenant_id"]
        if current_user["role"] != "master":
            tenant_id = existing["tenant_id"]

        cur.execute(
            """
            UPDATE agent_ui_user_profiles
            SET tenant_id = %s,
                name = %s,
                permissions = %s,
                is_active = %s,
                updated_at = NOW()
            WHERE id = %s
            RETURNING *
            """,
            (tenant_id, payload.name, Json(normalize_permissions(payload.permissions)), payload.is_active, profile_id),
        )
        row = cur.fetchone()
    return {"item": serialize_profile(row)}


@router.put("/api/user-profiles/{profile_id}/status")
def update_user_profile_status(profile_id: str, payload: ActiveStatePayload, current_user: dict = Depends(get_current_user)):
    require_permission(current_user, "user_profiles", "deactivate")
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT * FROM agent_ui_user_profiles WHERE id = %s LIMIT 1", (profile_id,))
        existing = cur.fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail="Perfil nao encontrado")
        if current_user["role"] != "master" and existing["tenant_id"] != current_user["tenant_id"]:
            raise HTTPException(status_code=403, detail="Usuario sem permissao nesse recurso")
        cur.execute(
            """
            UPDATE agent_ui_user_profiles
            SET is_active = %s,
                updated_at = NOW()
            WHERE id = %s
            RETURNING *
            """,
            (payload.is_active, profile_id),
        )
        row = cur.fetchone()
    return {"item": serialize_profile(row)}
