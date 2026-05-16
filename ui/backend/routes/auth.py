from fastapi import APIRouter, Depends, HTTPException

from ui.backend.core import config
from ui.backend.core.db import get_connection
from ui.backend.core.dependencies import create_session, get_current_user, serialize_user
from ui.backend.core.schemas import LoginRequest
from ui.backend.core.security import verify_password

router = APIRouter()


@router.post("/api/auth/login")
def login(payload: LoginRequest):
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT u.*, t.tenant_key, p.name AS profile_name, p.permissions AS profile_permissions
            FROM agent_ui_users u
            LEFT JOIN agent_ui_tenants t ON t.id = u.tenant_id
            LEFT JOIN agent_ui_user_profiles p ON p.id = u.profile_id
            WHERE u.email = %s
            LIMIT 1
            """,
            (payload.email.lower(),),
        )
        user = cur.fetchone()

    if not user or not verify_password(payload.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Usuário ou senha inválidos")
    if not user["is_active"]:
        raise HTTPException(status_code=403, detail="Usuário inativo")

    token = create_session(user["id"], config.UI_SESSION_HOURS)
    return {"token": token, "session_id": token, "user": serialize_user(user)}


@router.get("/api/auth/me")
def me(current_user: dict = Depends(get_current_user)):
    return {"user": serialize_user(current_user)}


@router.post("/api/auth/logout")
def logout(current_user: dict = Depends(get_current_user)):
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            UPDATE agent_ui_sessions
            SET revoked_at = NOW()
            WHERE token = %s
            """,
            (current_user["session_token"],),
        )
    return {"ok": True}
