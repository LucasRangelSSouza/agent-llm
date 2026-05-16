import asyncio

import httpx
from fastapi import HTTPException

from ui.backend.core import config
from ui.backend.core.db import get_connection, new_id
from ui.backend.core.dependencies import parse_sse_text_payload, safe_json_loads
from ui.backend.services.file_storage import save_file_bytes


def build_ai_url(path: str) -> str:
    root = (config.AI_API_ROOT_PATH or "").strip("/")
    suffix = path.lstrip("/")
    if root:
        return f"{config.AI_API_BASE_URL}/{root}/{suffix}"
    return f"{config.AI_API_BASE_URL}/{suffix}"


async def send_chat_message_to_ai(payload, current_user: dict, files=None) -> dict:
    chat_id = payload.chat_id
    uploaded_payloads = []
    stored_files = []

    with get_connection() as conn, conn.cursor() as cur:
        if chat_id:
            cur.execute(
                """
                SELECT *
                FROM agent_ui_chats
                WHERE id = %s AND user_id = %s
                LIMIT 1
                """,
                (chat_id, current_user["id"]),
            )
            chat = cur.fetchone()
        else:
            chat = None

        if not chat:
            chat_id = new_id()
            cur.execute(
                """
                INSERT INTO agent_ui_chats (id, user_id, tenant_id, title)
                VALUES (%s, %s, %s, %s)
                RETURNING *
                """,
                (
                    chat_id,
                    current_user["id"],
                    current_user["tenant_id"],
                    payload.question[:80],
                ),
            )
            chat = cur.fetchone()

    tenant_id = payload.tenant_id or current_user["tenant_id"]
    modules = payload.modules or config.AI_DEFAULT_MODULE
    active_template = None

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                d.template_id,
                d.template_version_id,
                t.name AS template_name,
                t.module_name,
                ten.tenant_key
            FROM agent_ui_template_deployments d
            JOIN agent_ui_templates t ON t.id = d.template_id
            JOIN agent_ui_tenants ten ON ten.id = d.tenant_id
            WHERE d.tenant_id = %s
              AND d.is_active = TRUE
            ORDER BY d.deployed_at DESC
            LIMIT 1
            """,
            (tenant_id,),
        )
        active_template = cur.fetchone()

    if active_template and active_template.get("module_name"):
        modules = active_template["module_name"]

    for uploaded in files or []:
        content = await uploaded.read()
        stored = save_file_bytes(
            tenant_id=tenant_id,
            user_id=current_user["id"],
            chat_id=chat_id,
            filename=uploaded.filename or "arquivo",
            content=content,
            content_type=uploaded.content_type or "application/octet-stream",
            kind="chat_upload",
            metadata={"source": "chat"},
        )
        stored_files.append(stored)
        uploaded_payloads.append(
            (
                "files",
                (
                    uploaded.filename,
                    content,
                    uploaded.content_type or "application/octet-stream",
                ),
            )
        )

    attachment_lines = []
    for stored in stored_files:
        attachment_lines.append(
            f"- [{stored['original_filename']}]({stored['public_url']})"
        )
    user_message_content = payload.question
    if attachment_lines:
        user_message_content = (
            f"{payload.question}\n\n"
            f"Arquivos anexados:\n"
            + "\n".join(attachment_lines)
        ).strip()

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO agent_ui_chat_messages (id, chat_id, role, content)
            VALUES (%s, %s, 'user', %s)
            """,
            (new_id(), chat_id, user_message_content),
        )

    request_timeout = httpx.Timeout(connect=15.0, read=120.0, write=30.0, pool=30.0)
    polling_timeout = httpx.Timeout(connect=10.0, read=15.0, write=15.0, pool=15.0)

    async with httpx.AsyncClient(timeout=request_timeout) as client:
        try:
            form_data = {
                    "question": payload.question,
                    "tenant_id": tenant_id,
                    "modules": modules,
                    "chat_id": chat_id,
                    "session_id": current_user.get("session_token") or chat_id,
                    "user_id": current_user["id"],
                    "template_id": active_template.get("template_id") if active_template else "",
                    "template_name": active_template.get("template_name") if active_template else "",
                    "template_version_id": active_template.get("template_version_id") if active_template else "",
                    "tenant_key": active_template.get("tenant_key") if active_template else "",
            }
            response = await client.post(
                build_ai_url("/avaliar"),
                data=form_data,
                files=uploaded_payloads or None,
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=502, detail=f"Falha ao iniciar requisicao na IA: {exc}") from exc

        job_payload = None
        try:
            job_payload = response.json()
        except ValueError:
            text_preview = response.text[:300] if response.text else ""
            raise HTTPException(status_code=502, detail=f"Resposta invalida ao iniciar job da IA: {text_preview}") from None

        job_id = job_payload.get("job_id") if isinstance(job_payload, dict) else None
        if not job_id:
            raise HTTPException(status_code=502, detail="Resposta da IA sem job_id ao iniciar processamento")

        final_answer = None
        for _ in range(900):
            try:
                result_response = await client.get(
                    build_ai_url(f"/resultado/{job_id}"),
                    timeout=polling_timeout,
                )
                result_response.raise_for_status()
            except (
                httpx.ReadError,
                httpx.ReadTimeout,
                httpx.ConnectError,
                httpx.RemoteProtocolError,
                httpx.PoolTimeout,
            ) as exc:
                print(f"UI polling recebeu erro transiente ao consultar resultado {job_id}: {exc}")
                await asyncio.sleep(1)
                continue
            except httpx.HTTPError as exc:
                print(f"UI polling recebeu erro HTTP ao consultar resultado {job_id}: {exc}")
                await asyncio.sleep(1)
                continue

            try:
                content_type = result_response.headers.get("content-type", "").lower()
                body_text = result_response.text
            except (
                httpx.ReadError,
                httpx.ReadTimeout,
                httpx.RemoteProtocolError,
            ) as exc:
                print(f"UI polling falhou ao ler o corpo do resultado {job_id}: {exc}")
                await asyncio.sleep(1)
                continue

            if "text/event-stream" in content_type:
                final_answer = parse_sse_text_payload(body_text)
                if final_answer:
                    break
            else:
                result_payload = safe_json_loads(body_text)
                if not isinstance(result_payload, dict):
                    print(
                        "UI polling recebeu resposta nao-JSON da IA:",
                        content_type,
                        repr(body_text[:300]),
                    )
                    await asyncio.sleep(1)
                    continue
                status = result_payload.get("status")
                if status == "done":
                    final_answer = result_payload.get("result", "")
                    break
                if status == "error":
                    raise HTTPException(status_code=500, detail=result_payload.get("error", "Erro na IA"))
            await asyncio.sleep(1)

    if final_answer is None:
        raise HTTPException(status_code=504, detail="Tempo excedido aguardando resposta da IA")

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO agent_ui_chat_messages (id, chat_id, role, content)
            VALUES (%s, %s, 'assistant', %s)
            """,
            (new_id(), chat_id, final_answer),
        )
        cur.execute(
            """
            UPDATE agent_ui_chats
            SET title = %s,
                updated_at = NOW()
            WHERE id = %s
            """,
            (payload.question[:80], chat_id),
        )

    return {"chat_id": chat_id, "answer": final_answer}
