from fastapi import APIRouter, Depends, HTTPException, Query

from ui.backend.core.db import get_connection, new_id
from ui.backend.core.dependencies import get_current_user, require_permission, serialize_user
from ui.backend.core.schemas import ActiveStatePayload, UserPayload, UserUpdatePayload
from ui.backend.core.security import hash_password

router = APIRouter()


@router.get("/api/users")
def list_users(include_inactive: bool = Query(False), current_user: dict = Depends(get_current_user)):
    require_permission(current_user, "users", "view")
    if include_inactive:
        require_permission(current_user, "users", "view_inactive")
    with get_connection() as conn, conn.cursor() as cur:
        if current_user["role"] == "master":
            cur.execute(
                """
                SELECT u.*, t.name AS tenant_name, p.name AS profile_name, p.permissions AS profile_permissions
                FROM agent_ui_users u
                LEFT JOIN agent_ui_tenants t ON t.id = u.tenant_id
                LEFT JOIN agent_ui_user_profiles p ON p.id = u.profile_id
                WHERE (%s = TRUE OR u.is_active = TRUE)
                ORDER BY u.full_name ASC
                """,
                (include_inactive,),
            )
        else:
            cur.execute(
                """
                SELECT u.*, t.name AS tenant_name, p.name AS profile_name, p.permissions AS profile_permissions
                FROM agent_ui_users u
                LEFT JOIN agent_ui_tenants t ON t.id = u.tenant_id
                LEFT JOIN agent_ui_user_profiles p ON p.id = u.profile_id
                WHERE u.tenant_id = %s
                  AND (%s = TRUE OR u.is_active = TRUE)
                ORDER BY u.full_name ASC
                """,
                (current_user["tenant_id"], include_inactive),
            )
        rows = cur.fetchall()
    return {
        "items": [
            {**serialize_user(row), "tenant_name": row.get("tenant_name")}
            for row in rows
        ]
    }


@router.post("/api/users")
def create_user(payload: UserPayload, current_user: dict = Depends(get_current_user)):
    require_permission(current_user, "users", "create")
    tenant_id = payload.tenant_id or current_user["tenant_id"]
    if current_user["role"] != "master":
        tenant_id = current_user["tenant_id"]
    user_id = new_id()
    with get_connection() as conn, conn.cursor() as cur:
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
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING *
            """,
            (
                user_id,
                tenant_id,
                payload.full_name,
                payload.email.lower(),
                payload.phone,
                payload.about,
                payload.role if current_user["role"] == "master" else "user",
                payload.profile_id,
                hash_password(payload.password),
                payload.is_active,
            ),
        )
        row = cur.fetchone()
    return {"item": serialize_user(row)}


@router.put("/api/users/{user_id}")
def update_user(user_id: str, payload: UserUpdatePayload, current_user: dict = Depends(get_current_user)):
    require_permission(current_user, "users", "edit")
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT * FROM agent_ui_users WHERE id = %s LIMIT 1", (user_id,))
        existing = cur.fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail="Usuário não encontrado")
        if current_user["role"] != "master" and existing["tenant_id"] != current_user["tenant_id"]:
            raise HTTPException(status_code=403, detail="Acesso negado")

        tenant_id = payload.tenant_id or existing["tenant_id"]
        if current_user["role"] != "master":
            tenant_id = existing["tenant_id"]

        password_hash = existing["password_hash"]
        if payload.password:
            password_hash = hash_password(payload.password)

        cur.execute(
            """
            UPDATE agent_ui_users
            SET tenant_id = %s,
                full_name = %s,
                email = %s,
                phone = %s,
                about = %s,
                role = %s,
                profile_id = %s,
                password_hash = %s,
                is_active = %s,
                updated_at = NOW()
            WHERE id = %s
            RETURNING *
            """,
            (
                tenant_id,
                payload.full_name,
                payload.email.lower(),
                payload.phone,
                payload.about,
                payload.role if current_user["role"] == "master" else existing["role"],
                payload.profile_id,
                password_hash,
                payload.is_active,
                user_id,
            ),
        )
        row = cur.fetchone()
    return {"item": serialize_user(row)}


@router.put("/api/users/{user_id}/status")
def update_user_status(user_id: str, payload: ActiveStatePayload, current_user: dict = Depends(get_current_user)):
    require_permission(current_user, "users", "deactivate")
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT * FROM agent_ui_users WHERE id = %s LIMIT 1", (user_id,))
        existing = cur.fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail="Usuário não encontrado")
        if current_user["role"] != "master" and existing["tenant_id"] != current_user["tenant_id"]:
            raise HTTPException(status_code=403, detail="Acesso negado")
        cur.execute(
            """
            UPDATE agent_ui_users
            SET is_active = %s,
                updated_at = NOW()
            WHERE id = %s
            RETURNING *
            """,
            (payload.is_active, user_id),
        )
        row = cur.fetchone()
    return {"item": serialize_user(row)}
