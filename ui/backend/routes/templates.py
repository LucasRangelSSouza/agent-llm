import json

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response

from ui.backend.core.dependencies import get_current_user, require_permission
from ui.backend.core.schemas import ActiveStatePayload, TemplateDeployPayload, TemplateVersionPayload
from ui.backend.domains.templates import (
    delete_template,
    deploy_template_version,
    export_template_json,
    get_template_detail,
    get_toolkit_catalog,
    get_version_payload,
    list_templates,
    require_template_manager,
    save_template_version,
    set_template_active,
)

router = APIRouter()


@router.get("/api/templates-legacy-placeholder")
def templates_placeholder(current_user: dict = Depends(get_current_user)):
    return {"items": [], "message": "Tela de templates entra na próxima rodada"}


@router.get("/api/toolkits")
def list_toolkits(current_user: dict = Depends(get_current_user)):
    require_permission(current_user, "templates", "view")
    return get_toolkit_catalog()


@router.get("/api/templates")
def api_list_templates(include_inactive: bool = Query(False), current_user: dict = Depends(get_current_user)):
    require_permission(current_user, "templates", "view")
    if include_inactive:
        require_permission(current_user, "templates", "view_inactive")
    try:
        require_template_manager(current_user)
        return {"items": list_templates(current_user, include_inactive=include_inactive)}
    except PermissionError as error:
        raise HTTPException(status_code=403, detail=str(error)) from error


@router.get("/api/templates/{template_id}")
def api_get_template(template_id: str, current_user: dict = Depends(get_current_user)):
    require_permission(current_user, "templates", "view")
    try:
        require_template_manager(current_user)
        return get_template_detail(template_id, current_user)
    except PermissionError as error:
        raise HTTPException(status_code=403, detail=str(error)) from error
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.get("/api/templates/{template_id}/export")
def api_export_template(template_id: str, version_id: str | None = Query(None), current_user: dict = Depends(get_current_user)):
    require_permission(current_user, "templates", "view")
    try:
        require_template_manager(current_user)
        filename, payload = export_template_json(template_id, current_user, version_id=version_id)
        return Response(
            content=json.dumps(payload, ensure_ascii=False, indent=2),
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    except PermissionError as error:
        raise HTTPException(status_code=403, detail=str(error)) from error
    except (ValueError, KeyError) as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.get("/api/template-versions/{version_id}")
def api_get_template_version(version_id: str, current_user: dict = Depends(get_current_user)):
    require_permission(current_user, "templates", "view")
    try:
        require_template_manager(current_user)
        return {"item": get_version_payload(version_id, current_user)}
    except PermissionError as error:
        raise HTTPException(status_code=403, detail=str(error)) from error
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.post("/api/templates")
def api_create_template(payload: TemplateVersionPayload, current_user: dict = Depends(get_current_user)):
    require_permission(current_user, "templates", "create")
    try:
        return {
            "item": save_template_version(
                payload.model_dump(),
                current_user,
                based_on_version_id=payload.based_on_version_id,
            )
        }
    except PermissionError as error:
        raise HTTPException(status_code=403, detail=str(error)) from error
    except (ValueError, KeyError) as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.post("/api/templates/{template_id}/versions")
def api_create_template_version(template_id: str, payload: TemplateVersionPayload, current_user: dict = Depends(get_current_user)):
    require_permission(current_user, "templates", "edit")
    try:
        return {
            "item": save_template_version(
                payload.model_dump(),
                current_user,
                template_id=template_id,
                based_on_version_id=payload.based_on_version_id,
            )
        }
    except PermissionError as error:
        raise HTTPException(status_code=403, detail=str(error)) from error
    except (ValueError, KeyError) as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.delete("/api/templates/{template_id}")
def api_delete_template(template_id: str, current_user: dict = Depends(get_current_user)):
    require_permission(current_user, "templates", "deactivate")
    try:
        delete_template(template_id, current_user)
        return {"ok": True}
    except PermissionError as error:
        raise HTTPException(status_code=403, detail=str(error)) from error
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.put("/api/templates/{template_id}/status")
def api_update_template_status(template_id: str, payload: ActiveStatePayload, current_user: dict = Depends(get_current_user)):
    require_permission(current_user, "templates", "deactivate")
    try:
        set_template_active(template_id, payload.is_active, current_user)
        return {"ok": True}
    except PermissionError as error:
        raise HTTPException(status_code=403, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.post("/api/templates/deploy")
def api_deploy_template(payload: TemplateDeployPayload, current_user: dict = Depends(get_current_user)):
    require_permission(current_user, "templates", "edit")
    try:
        return {"item": deploy_template_version(payload.template_id, payload.version_id, current_user)}
    except PermissionError as error:
        raise HTTPException(status_code=403, detail=str(error)) from error
    except (ValueError, KeyError) as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
