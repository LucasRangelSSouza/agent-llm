from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile

from ui.backend.core.db import get_connection, new_id
from ui.backend.core.dependencies import get_current_user
from ui.backend.core.schemas import ChatSendPayload
from ui.backend.services.chat_service import send_chat_message_to_ai

router = APIRouter()


@router.get("/api/chats")
def list_chats(current_user: dict = Depends(get_current_user)):
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT *
            FROM agent_ui_chats
            WHERE user_id = %s
              AND COALESCE(is_hidden, FALSE) = FALSE
            ORDER BY updated_at DESC
            """,
            (current_user["id"],),
        )
        rows = cur.fetchall()
    return {"items": rows}


@router.post("/api/chats")
def create_chat(current_user: dict = Depends(get_current_user)):
    chat_id = new_id()
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO agent_ui_chats (id, user_id, tenant_id, title)
            VALUES (%s, %s, %s, %s)
            RETURNING *
            """,
            (chat_id, current_user["id"], current_user["tenant_id"], "Novo chat"),
        )
        row = cur.fetchone()
    return {"item": row}


@router.get("/api/chats/{chat_id}/messages")
def list_chat_messages(chat_id: str, current_user: dict = Depends(get_current_user)):
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT *
            FROM agent_ui_chats
            WHERE id = %s
              AND user_id = %s
            LIMIT 1
            """,
            (chat_id, current_user["id"]),
        )
        chat = cur.fetchone()
        if not chat:
            raise HTTPException(status_code=404, detail="Chat nao encontrado")
        cur.execute(
            """
            SELECT *
            FROM agent_ui_chat_messages
            WHERE chat_id = %s
            ORDER BY created_at ASC
            """,
            (chat_id,),
        )
        rows = cur.fetchall()
    return {"items": rows}


@router.put("/api/chats/{chat_id}/hide")
def hide_chat(chat_id: str, current_user: dict = Depends(get_current_user)):
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            UPDATE agent_ui_chats
            SET is_hidden = TRUE,
                updated_at = NOW()
            WHERE id = %s
              AND user_id = %s
            RETURNING *
            """,
            (chat_id, current_user["id"]),
        )
        row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Chat nao encontrado")
    return {"item": row}


@router.put("/api/chats/hide-all")
def hide_all_chats(current_user: dict = Depends(get_current_user)):
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            UPDATE agent_ui_chats
            SET is_hidden = TRUE,
                updated_at = NOW()
            WHERE user_id = %s
              AND COALESCE(is_hidden, FALSE) = FALSE
            """,
            (current_user["id"],),
        )
    return {"ok": True}


@router.post("/api/chat/send")
async def send_chat_message(request: Request, current_user: dict = Depends(get_current_user)):
    content_type = request.headers.get("content-type", "")
    files: list[UploadFile] = []
    if "multipart/form-data" in content_type:
        form = await request.form()
        payload = ChatSendPayload(
            chat_id=form.get("chat_id") or None,
            question=str(form.get("question") or ""),
            modules=form.get("modules") or None,
            tenant_id=form.get("tenant_id") or None,
        )
        for value in form.getlist("files"):
            if hasattr(value, "filename") and hasattr(value, "read"):
                files.append(value)
    else:
        payload = ChatSendPayload(**(await request.json()))
    return await send_chat_message_to_ai(payload, current_user, files=files)
