from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile

from ui.backend.core.db import get_connection, new_id
from ui.backend.core.dependencies import get_current_user, get_file_or_404, require_permission
from ui.backend.core.schemas import ActiveStatePayload
from ui.backend.services.file_storage import save_file_bytes

router = APIRouter()


def _serialize_file(row: dict, include_form: bool = False) -> dict:
    item = {
        "id": row["id"],
        "tenant_id": row["tenant_id"],
        "tenant_name": row.get("tenant_name"),
        "name": row["name"],
        "description": row.get("description") or "",
        "storage_file_id": row.get("storage_file_id"),
        "original_filename": row.get("original_filename") or "",
        "file_url": row.get("file_url") or "",
        "content_type": row.get("content_type") or "",
        "size_bytes": int(row.get("size_bytes") or 0),
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
            "is_active": row.get("is_active", True),
            "original_filename": row.get("original_filename") or "",
            "file_url": row.get("file_url") or "",
            "content_type": row.get("content_type") or "",
            "size_bytes": int(row.get("size_bytes") or 0),
        }
    return item


@router.get("/api/files")
def list_files(include_inactive: bool = Query(False), current_user: dict = Depends(get_current_user)):
    require_permission(current_user, "files", "view")
    if include_inactive:
        require_permission(current_user, "files", "view_inactive")

    with get_connection() as conn, conn.cursor() as cur:
        if current_user["role"] == "master":
            cur.execute(
                """
                SELECT f.*, t.name AS tenant_name
                FROM agent_ui_files f
                LEFT JOIN agent_ui_tenants t ON t.id = f.tenant_id
                WHERE (%s = TRUE OR f.is_active = TRUE)
                ORDER BY f.updated_at DESC, f.name ASC
                """,
                (include_inactive,),
            )
        else:
            cur.execute(
                """
                SELECT f.*, t.name AS tenant_name
                FROM agent_ui_files f
                LEFT JOIN agent_ui_tenants t ON t.id = f.tenant_id
                WHERE f.tenant_id = %s
                  AND (%s = TRUE OR f.is_active = TRUE)
                ORDER BY f.updated_at DESC, f.name ASC
                """,
                (current_user["tenant_id"], include_inactive),
            )
        rows = cur.fetchall()
    return {"items": [_serialize_file(row) for row in rows]}


@router.get("/api/files/{file_id}")
def get_file(file_id: str, current_user: dict = Depends(get_current_user)):
    require_permission(current_user, "files", "view")
    row = get_file_or_404(file_id, current_user)
    return {"item": _serialize_file(row, include_form=True)}


@router.post("/api/files")
async def create_file(
    name: str = Form(...),
    tenant_id: str | None = Form(default=None),
    description: str = Form(default=""),
    is_active: bool = Form(default=True),
    upload: UploadFile = File(...),
    current_user: dict = Depends(get_current_user),
):
    require_permission(current_user, "files", "create")
    final_tenant_id = tenant_id or current_user["tenant_id"]
    if current_user["role"] != "master":
        final_tenant_id = current_user["tenant_id"]
    content = await upload.read()
    stored = save_file_bytes(
        tenant_id=final_tenant_id,
        user_id=current_user["id"],
        chat_id=None,
        filename=upload.filename or name,
        content=content,
        content_type=upload.content_type,
        kind="tenant_file",
        metadata={"registry_name": name},
        path_prefix=f"tenants/{final_tenant_id}/registry/files",
    )

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO agent_ui_files (
                id, tenant_id, name, description, storage_file_id, original_filename,
                file_url, content_type, size_bytes, is_active, created_by, updated_by
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING *
            """,
            (
                new_id(),
                final_tenant_id,
                name.strip(),
                description or "",
                stored["id"],
                stored["original_filename"],
                stored["public_url"],
                stored["content_type"],
                stored["size_bytes"],
                is_active,
                current_user["id"],
                current_user["id"],
            ),
        )
        row = cur.fetchone()
        cur.execute("SELECT name AS tenant_name FROM agent_ui_tenants WHERE id = %s", (row["tenant_id"],))
        tenant_row = cur.fetchone()
        row["tenant_name"] = tenant_row["tenant_name"] if tenant_row else None
    return {"item": _serialize_file(row, include_form=True)}


@router.put("/api/files/{file_id}")
async def update_file(
    file_id: str,
    name: str = Form(...),
    tenant_id: str | None = Form(default=None),
    description: str = Form(default=""),
    is_active: bool = Form(default=True),
    upload: UploadFile | None = File(default=None),
    current_user: dict = Depends(get_current_user),
):
    require_permission(current_user, "files", "edit")
    existing = get_file_or_404(file_id, current_user)
    final_tenant_id = tenant_id or existing["tenant_id"]
    if current_user["role"] != "master":
        final_tenant_id = existing["tenant_id"]

    storage_file_id = existing.get("storage_file_id")
    original_filename = existing.get("original_filename") or ""
    file_url = existing.get("file_url") or ""
    content_type = existing.get("content_type") or ""
    size_bytes = int(existing.get("size_bytes") or 0)

    if upload and upload.filename:
        content = await upload.read()
        stored = save_file_bytes(
            tenant_id=final_tenant_id,
            user_id=current_user["id"],
            chat_id=None,
            filename=upload.filename,
            content=content,
            content_type=upload.content_type,
            kind="tenant_file",
            metadata={"registry_name": name, "replaced_file_id": file_id},
            path_prefix=f"tenants/{final_tenant_id}/registry/files",
        )
        storage_file_id = stored["id"]
        original_filename = stored["original_filename"]
        file_url = stored["public_url"]
        content_type = stored["content_type"]
        size_bytes = stored["size_bytes"]

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            UPDATE agent_ui_files
            SET tenant_id = %s,
                name = %s,
                description = %s,
                storage_file_id = %s,
                original_filename = %s,
                file_url = %s,
                content_type = %s,
                size_bytes = %s,
                is_active = %s,
                updated_by = %s,
                updated_at = NOW()
            WHERE id = %s
            RETURNING *
            """,
            (
                final_tenant_id,
                name.strip(),
                description or "",
                storage_file_id,
                original_filename,
                file_url,
                content_type,
                size_bytes,
                is_active,
                current_user["id"],
                file_id,
            ),
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Arquivo nao encontrado")
        cur.execute("SELECT name AS tenant_name FROM agent_ui_tenants WHERE id = %s", (row["tenant_id"],))
        tenant_row = cur.fetchone()
        row["tenant_name"] = tenant_row["tenant_name"] if tenant_row else None
    return {"item": _serialize_file(row, include_form=True)}


@router.put("/api/files/{file_id}/status")
def update_file_status(file_id: str, payload: ActiveStatePayload, current_user: dict = Depends(get_current_user)):
    require_permission(current_user, "files", "deactivate")
    row = get_file_or_404(file_id, current_user)
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            UPDATE agent_ui_files
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
    return {"item": _serialize_file(updated, include_form=True)}
