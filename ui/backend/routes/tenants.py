from fastapi import APIRouter, Depends, HTTPException, Query

from ui.backend.core.db import get_connection, new_id
from ui.backend.core.dependencies import get_current_user, require_master, serialize_tenant
from ui.backend.core.migrations import ensure_default_profiles
from ui.backend.core.schemas import ActiveStatePayload, TenantPayload

router = APIRouter()


@router.get("/api/tenants")
def list_tenants(include_inactive: bool = Query(False), current_user: dict = Depends(get_current_user)):
    require_master(current_user)
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT *
            FROM agent_ui_tenants
            WHERE (%s = TRUE OR is_active = TRUE)
            ORDER BY name ASC
            """,
            (include_inactive,),
        )
        rows = cur.fetchall()
    return {"items": [serialize_tenant(row) for row in rows]}


@router.post("/api/tenants")
def create_tenant(payload: TenantPayload, current_user: dict = Depends(get_current_user)):
    require_master(current_user)
    tenant_id = new_id()
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO agent_ui_tenants (id, name, cnpj, legal_name)
            VALUES (%s, %s, %s, %s)
            RETURNING *
            """,
            (tenant_id, payload.name, payload.cnpj, payload.legal_name),
        )
        row = cur.fetchone()
        ensure_default_profiles(cur, tenant_id)
    return {"item": serialize_tenant(row)}


@router.put("/api/tenants/{tenant_id}")
def update_tenant(tenant_id: str, payload: TenantPayload, current_user: dict = Depends(get_current_user)):
    require_master(current_user)
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            UPDATE agent_ui_tenants
            SET name = %s,
                cnpj = %s,
                legal_name = %s,
                updated_at = NOW()
            WHERE id = %s
            RETURNING *
            """,
            (payload.name, payload.cnpj, payload.legal_name, tenant_id),
        )
        row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Tenant não encontrado")
    return {"item": serialize_tenant(row)}


@router.put("/api/tenants/{tenant_id}/status")
def update_tenant_status(tenant_id: str, payload: ActiveStatePayload, current_user: dict = Depends(get_current_user)):
    require_master(current_user)
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            UPDATE agent_ui_tenants
            SET is_active = %s,
                updated_at = NOW()
            WHERE id = %s
            RETURNING *
            """,
            (payload.is_active, tenant_id),
        )
        row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Tenant não encontrado")
    return {"item": serialize_tenant(row)}
