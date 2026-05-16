from ui.backend.domains.templates.bootstrap import bootstrap_legacy_templates, ensure_tenant_keys
from ui.backend.domains.templates.service import (
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

__all__ = [
    "bootstrap_legacy_templates",
    "delete_template",
    "deploy_template_version",
    "ensure_tenant_keys",
    "export_template_json",
    "get_template_detail",
    "get_toolkit_catalog",
    "get_version_payload",
    "list_templates",
    "require_template_manager",
    "save_template_version",
    "set_template_active",
]
