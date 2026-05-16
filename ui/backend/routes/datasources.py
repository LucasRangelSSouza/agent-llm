import json

from fastapi import APIRouter, Depends, HTTPException, Query

from ui.backend.domains.datasources import (
    build_datasource_payload,
    require_datasource_manager,
    serialize_datasource,
    test_datasource_connection,
)
from ui.backend.core.db import get_connection, new_id
from ui.backend.core.dependencies import get_current_user, get_datasource_or_404, require_permission
from ui.backend.core.schemas import ActiveStatePayload, DatasourcePayload

router = APIRouter()


@router.get("/api/datasources")
def list_datasources(include_inactive: bool = Query(False), current_user: dict = Depends(get_current_user)):
    require_permission(current_user, "datasources", "view")
    if include_inactive:
        require_permission(current_user, "datasources", "view_inactive")
    try:
        require_datasource_manager(current_user)
    except PermissionError as error:
        raise HTTPException(status_code=403, detail=str(error)) from error

    with get_connection() as conn, conn.cursor() as cur:
        if current_user["role"] == "master":
            cur.execute(
                """
                SELECT d.*, t.name AS tenant_name
                FROM agent_ui_datasources d
                LEFT JOIN agent_ui_tenants t ON t.id = d.tenant_id
                WHERE (%s = TRUE OR d.is_active = TRUE)
                ORDER BY d.created_at DESC
                """,
                (include_inactive,),
            )
        else:
            cur.execute(
                """
                SELECT d.*, t.name AS tenant_name
                FROM agent_ui_datasources d
                LEFT JOIN agent_ui_tenants t ON t.id = d.tenant_id
                WHERE d.tenant_id = %s
                  AND (%s = TRUE OR d.is_active = TRUE)
                ORDER BY d.created_at DESC
                """,
                (current_user["tenant_id"], include_inactive),
            )
        rows = cur.fetchall()

    return {"items": [serialize_datasource(row) for row in rows]}


@router.get("/api/datasources/{datasource_id}")
def get_datasource(datasource_id: str, current_user: dict = Depends(get_current_user)):
    require_permission(current_user, "datasources", "view")
    try:
        require_datasource_manager(current_user)
    except PermissionError as error:
        raise HTTPException(status_code=403, detail=str(error)) from error
    row = get_datasource_or_404(datasource_id, current_user)
    return {"item": serialize_datasource(row, include_edit_payload=True)}


@router.post("/api/datasources/test")
def test_datasource(payload: DatasourcePayload, current_user: dict = Depends(get_current_user)):
    require_permission(current_user, "datasources", "edit" if payload.datasource_id else "create")
    try:
        existing = None
        if payload.datasource_id:
            existing = get_datasource_or_404(payload.datasource_id, current_user)
        tenant_id, config_json, secret_json, meta = build_datasource_payload(
            payload.model_dump(),
            current_user,
            existing=existing,
        )
        result = test_datasource_connection(meta["kind"], config_json, secret_json)
        return {
            "ok": True,
            "tenant_id": tenant_id,
            "message": result["message"],
            "summary": {"kind": meta["kind"], "name": meta["name"]},
        }
    except PermissionError as error:
        raise HTTPException(status_code=403, detail=str(error)) from error
    except Exception as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.post("/api/datasources")
def create_datasource(payload: DatasourcePayload, current_user: dict = Depends(get_current_user)):
    require_permission(current_user, "datasources", "create")
    try:
        tenant_id, config_json, secret_json, meta = build_datasource_payload(
            payload.model_dump(),
            current_user,
        )
    except PermissionError as error:
        raise HTTPException(status_code=403, detail=str(error)) from error
    except Exception as error:
        raise HTTPException(status_code=400, detail=str(error)) from error

    datasource_id = new_id()
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO agent_ui_datasources (
                id,
                tenant_id,
                name,
                kind,
                description,
                config_json,
                secret_json,
                is_active,
                last_test_status,
                last_test_message,
                last_test_at,
                created_by,
                updated_by
            )
            VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s, 'ok', 'Conexao validada antes do save', NOW(), %s, %s)
            RETURNING *
            """,
            (
                datasource_id,
                tenant_id,
                meta["name"],
                meta["kind"],
                meta["description"],
                json.dumps(config_json, ensure_ascii=False),
                json.dumps(secret_json, ensure_ascii=False),
                meta["is_active"],
                current_user["id"],
                current_user["id"],
            ),
        )
        row = cur.fetchone()

    return {"item": serialize_datasource(row, include_edit_payload=True)}


@router.put("/api/datasources/{datasource_id}")
def update_datasource(datasource_id: str, payload: DatasourcePayload, current_user: dict = Depends(get_current_user)):
    require_permission(current_user, "datasources", "edit")
    existing = get_datasource_or_404(datasource_id, current_user)

    try:
        tenant_id, config_json, secret_json, meta = build_datasource_payload(
            payload.model_dump(),
            current_user,
            existing=existing,
        )
    except PermissionError as error:
        raise HTTPException(status_code=403, detail=str(error)) from error
    except Exception as error:
        raise HTTPException(status_code=400, detail=str(error)) from error

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            UPDATE agent_ui_datasources
            SET tenant_id = %s,
                name = %s,
                kind = %s,
                description = %s,
                config_json = %s::jsonb,
                secret_json = %s::jsonb,
                is_active = %s,
                last_test_status = 'ok',
                last_test_message = 'Conexao validada antes do save',
                last_test_at = NOW(),
                updated_by = %s,
                updated_at = NOW()
            WHERE id = %s
            RETURNING *
            """,
            (
                tenant_id,
                meta["name"],
                meta["kind"],
                meta["description"],
                json.dumps(config_json, ensure_ascii=False),
                json.dumps(secret_json, ensure_ascii=False),
                meta["is_active"],
                current_user["id"],
                datasource_id,
            ),
        )
        row = cur.fetchone()

    return {"item": serialize_datasource(row, include_edit_payload=True)}


@router.put("/api/datasources/{datasource_id}/status")
def update_datasource_status(datasource_id: str, payload: ActiveStatePayload, current_user: dict = Depends(get_current_user)):
    require_permission(current_user, "datasources", "deactivate")
    row = get_datasource_or_404(datasource_id, current_user)
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            UPDATE agent_ui_datasources
            SET is_active = %s,
                updated_by = %s,
                updated_at = NOW()
            WHERE id = %s
            RETURNING *
            """,
            (payload.is_active, current_user["id"], row["id"]),
        )
        updated = cur.fetchone()
    return {"item": serialize_datasource(updated, include_edit_payload=True)}
