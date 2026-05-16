import json

from fastapi import APIRouter, Depends, HTTPException, Query

from ui.backend.core.db import get_connection, new_id
from ui.backend.core.dependencies import get_ai_service_or_404, get_current_user, require_permission
from ui.backend.core.schemas import AIServicePayload, ActiveStatePayload
from ui.backend.domains.ai_services import (
    build_ai_service_payload,
    get_ai_service_catalog,
    require_ai_service_manager,
    serialize_ai_service,
)

router = APIRouter()


@router.get("/api/ai-services/catalog")
def list_ai_service_catalog(current_user: dict = Depends(get_current_user)):
    require_permission(current_user, "ai_services", "view")
    try:
        require_ai_service_manager(current_user)
    except PermissionError as error:
        raise HTTPException(status_code=403, detail=str(error)) from error
    return get_ai_service_catalog()


@router.get("/api/ai-services")
def list_ai_services(include_inactive: bool = Query(False), current_user: dict = Depends(get_current_user)):
    require_permission(current_user, "ai_services", "view")
    if include_inactive:
        require_permission(current_user, "ai_services", "view_inactive")
    try:
        require_ai_service_manager(current_user)
    except PermissionError as error:
        raise HTTPException(status_code=403, detail=str(error)) from error

    with get_connection() as conn, conn.cursor() as cur:
        if current_user["role"] == "master":
            cur.execute(
                """
                SELECT s.*, t.name AS tenant_name
                FROM agent_ui_ai_services s
                LEFT JOIN agent_ui_tenants t ON t.id = s.tenant_id
                WHERE (%s = TRUE OR s.is_active = TRUE)
                ORDER BY s.created_at DESC, s.name ASC
                """,
                (include_inactive,),
            )
        else:
            cur.execute(
                """
                SELECT s.*, t.name AS tenant_name
                FROM agent_ui_ai_services s
                LEFT JOIN agent_ui_tenants t ON t.id = s.tenant_id
                WHERE s.tenant_id = %s
                  AND (%s = TRUE OR s.is_active = TRUE)
                ORDER BY s.created_at DESC, s.name ASC
                """,
                (current_user["tenant_id"], include_inactive),
            )
        rows = cur.fetchall()

    return {"items": [serialize_ai_service(row) for row in rows]}


@router.get("/api/ai-services/{ai_service_id}")
def get_ai_service(ai_service_id: str, current_user: dict = Depends(get_current_user)):
    require_permission(current_user, "ai_services", "view")
    try:
        require_ai_service_manager(current_user)
    except PermissionError as error:
        raise HTTPException(status_code=403, detail=str(error)) from error

    row = get_ai_service_or_404(ai_service_id, current_user)
    return {"item": serialize_ai_service(row, include_edit_payload=True)}


@router.post("/api/ai-services")
def create_ai_service(payload: AIServicePayload, current_user: dict = Depends(get_current_user)):
    require_permission(current_user, "ai_services", "create")
    try:
        tenant_id, config_json, secret_json, meta = build_ai_service_payload(payload.model_dump(), current_user)
    except PermissionError as error:
        raise HTTPException(status_code=403, detail=str(error)) from error
    except Exception as error:
        raise HTTPException(status_code=400, detail=str(error)) from error

    ai_service_id = new_id()
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO agent_ui_ai_services (
                id, tenant_id, provider, name, description, model_name,
                config_json, secret_json, is_active, created_by, updated_by
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s, %s, %s)
            RETURNING *
            """,
            (
                ai_service_id,
                tenant_id,
                meta["provider"],
                meta["name"],
                meta["description"],
                meta["model_name"],
                json.dumps(config_json, ensure_ascii=False),
                json.dumps(secret_json, ensure_ascii=False),
                meta["is_active"],
                current_user["id"],
                current_user["id"],
            ),
        )
        row = cur.fetchone()

    return {"item": serialize_ai_service(row, include_edit_payload=True)}


@router.put("/api/ai-services/{ai_service_id}")
def update_ai_service(ai_service_id: str, payload: AIServicePayload, current_user: dict = Depends(get_current_user)):
    require_permission(current_user, "ai_services", "edit")
    existing = get_ai_service_or_404(ai_service_id, current_user)
    try:
        tenant_id, config_json, secret_json, meta = build_ai_service_payload(
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
            UPDATE agent_ui_ai_services
            SET tenant_id = %s,
                provider = %s,
                name = %s,
                description = %s,
                model_name = %s,
                config_json = %s::jsonb,
                secret_json = %s::jsonb,
                is_active = %s,
                updated_by = %s,
                updated_at = NOW()
            WHERE id = %s
            RETURNING *
            """,
            (
                tenant_id,
                meta["provider"],
                meta["name"],
                meta["description"],
                meta["model_name"],
                json.dumps(config_json, ensure_ascii=False),
                json.dumps(secret_json, ensure_ascii=False),
                meta["is_active"],
                current_user["id"],
                ai_service_id,
            ),
        )
        row = cur.fetchone()

    return {"item": serialize_ai_service(row, include_edit_payload=True)}


@router.put("/api/ai-services/{ai_service_id}/status")
def update_ai_service_status(ai_service_id: str, payload: ActiveStatePayload, current_user: dict = Depends(get_current_user)):
    require_permission(current_user, "ai_services", "deactivate")
    row = get_ai_service_or_404(ai_service_id, current_user)
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            UPDATE agent_ui_ai_services
            SET is_active = %s,
                updated_by = %s,
                updated_at = NOW()
            WHERE id = %s
            RETURNING *
            """,
            (payload.is_active, current_user["id"], row["id"]),
        )
        updated = cur.fetchone()
    return {"item": serialize_ai_service(updated, include_edit_payload=True)}
