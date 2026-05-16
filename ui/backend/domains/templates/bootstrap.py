import json
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import unquote, urlparse

from psycopg2.extras import Json

from ui.backend.core import config
from ui.backend.core.db import get_connection, new_id
from ui.backend.domains.templates.service import deploy_template_version, save_template_version


def ensure_default_ai_service(tenant_id: str, user_id: Optional[str]) -> str:
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT id
            FROM agent_ui_ai_services
            WHERE tenant_id = %s
            ORDER BY created_at ASC
            LIMIT 1
            """,
            (tenant_id,),
        )
        existing = cur.fetchone()
        if existing:
            return existing["id"]

        provider = "local_gguf"
        service_name = "Local GGUF basico"
        model_value = "Qwen2.5-3B-Instruct-GGUF"
        config_json = {
            "provider": provider,
            "endpoint_url": "",
            "organization_id": "",
            "suggested_models": [model_value],
        }
        secret_json = {"api_key": ""}

        service_id = new_id()
        cur.execute(
            """
            INSERT INTO agent_ui_ai_services (
                id, tenant_id, provider, name, description, model_name,
                config_json, secret_json, is_active, created_by, updated_by
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, TRUE, %s, %s)
            RETURNING id
            """,
            (
                service_id,
                tenant_id,
                provider,
                service_name,
                "Servico inicial criado automaticamente para bootstrap do sistema",
                model_value,
                Json(config_json),
                Json(secret_json),
                user_id,
                user_id,
            ),
        )
        return cur.fetchone()["id"]


def ensure_tenant_keys() -> None:
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT id, name, tenant_key FROM agent_ui_tenants ORDER BY created_at, name")
        rows = cur.fetchall()
        used = set()
        for row in rows:
            current = (row.get("tenant_key") or "").strip()
            candidate = current or row["name"]
            candidate = candidate.lower().strip()
            candidate = "".join(ch if ch.isalnum() else "_" for ch in candidate)
            candidate = "_".join(part for part in candidate.split("_") if part) or "tenant"
            base_candidate = candidate
            suffix = 2
            while candidate in used:
                candidate = f"{base_candidate}_{suffix}"
                suffix += 1
            cur.execute(
                "UPDATE agent_ui_tenants SET tenant_key = %s WHERE id = %s",
                (candidate, row["id"]),
            )
            used.add(candidate)


def _convert_legacy_db_connection(tenant_id: str, conn_name: str, conn_info: dict, user_id: Optional[str]) -> str:
    uri = (conn_info or {}).get("uri") or "sqlite:///:memory:"
    description = (conn_info or {}).get("description") or conn_name
    parsed = urlparse(uri)
    kind = "sqlite"
    config_json: Dict[str, Any] = {}
    secret_json: Dict[str, Any] = {}

    if uri.startswith("sqlite"):
        path = uri.replace("sqlite:///", "", 1) if uri != "sqlite:///:memory:" else ":memory:"
        config_json = {"sqlite_mode": "path", "sqlite_path": path, "sqlite_url": ""}
    elif parsed.scheme.startswith("postgresql"):
        kind = "postgresql"
        config_json = {
            "host": parsed.hostname or "",
            "port": parsed.port or 5432,
            "database_name": parsed.path.lstrip("/"),
            "schema_name": "",
            "username": parsed.username or "",
            "ssl_mode": "",
        }
        secret_json = {"password": unquote(parsed.password or "")}
    elif parsed.scheme.startswith("mysql"):
        kind = "mysql"
        config_json = {
            "host": parsed.hostname or "",
            "port": parsed.port or 3306,
            "database_name": parsed.path.lstrip("/"),
            "schema_name": "",
            "username": parsed.username or "",
            "ssl_mode": "",
        }
        secret_json = {"password": unquote(parsed.password or "")}
    else:
        config_json = {"sqlite_mode": "path", "sqlite_path": ":memory:", "sqlite_url": ""}

    datasource_id = new_id()
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO agent_ui_datasources (
                id, tenant_id, name, kind, description,
                config_json, secret_json, is_active,
                last_test_status, last_test_message, last_test_at, created_by, updated_by
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, TRUE, 'imported', 'Importado do agent_template.json', NOW(), %s, %s)
            RETURNING id
            """,
            (
                datasource_id,
                tenant_id,
                conn_name,
                kind,
                description,
                Json(config_json),
                Json(secret_json),
                user_id,
                user_id,
            ),
        )
        return cur.fetchone()["id"]


def _convert_legacy_athena_connection(tenant_id: str, module_name: str, athena_info: dict, user_id: Optional[str]) -> str:
    datasource_id = new_id()
    config_json = {
        "database_name": athena_info.get("database") or "",
        "catalog_name": athena_info.get("catalog_name") or "AwsDataCatalog",
        "region_name": athena_info.get("region_name") or "us-east-1",
        "output_location": athena_info.get("output_location") or "",
        "workgroup": athena_info.get("workgroup") or "",
        "aws_access_key_id": "",
    }
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO agent_ui_datasources (
                id, tenant_id, name, kind, description,
                config_json, secret_json, is_active,
                last_test_status, last_test_message, last_test_at, created_by, updated_by
            )
            VALUES (%s, %s, %s, 'athena', %s, %s, %s, TRUE, 'imported', 'Importado do agent_template.json', NOW(), %s, %s)
            RETURNING id
            """,
            (
                datasource_id,
                tenant_id,
                f"{module_name} Athena",
                f"Datasource Athena importado do template legado do módulo {module_name}",
                Json(config_json),
                Json({}),
                user_id,
                user_id,
            ),
        )
        return cur.fetchone()["id"]


def bootstrap_legacy_templates() -> None:
    ensure_tenant_keys()
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) AS total FROM agent_ui_templates WHERE is_deleted = FALSE")
        if cur.fetchone()["total"] > 0:
            return
        cur.execute(
            """
            SELECT u.id, u.tenant_id, t.tenant_key
            FROM agent_ui_users u
            JOIN agent_ui_tenants t ON t.id = u.tenant_id
            WHERE u.role = 'master'
            ORDER BY u.created_at
            LIMIT 1
            """
        )
        owner = cur.fetchone()
        if not owner:
            return

    template_path = Path(config.BASE_DIR) / config.LEGACY_AGENT_TEMPLATE_PATH
    if not template_path.exists():
        return

    legacy_data = json.loads(template_path.read_text(encoding="utf-8"))
    current_user = {"id": owner["id"], "tenant_id": owner["tenant_id"], "role": "master"}
    default_ai_service_id = ensure_default_ai_service(owner["tenant_id"], owner["id"])

    for module_name, module_data in legacy_data.items():
        datasource_ids = []
        for conn_name, conn_info in (module_data.get("DB_connections") or {}).items():
            datasource_ids.append(_convert_legacy_db_connection(owner["tenant_id"], conn_name, conn_info, owner["id"]))
        athena_info = module_data.get("athena_connection")
        if isinstance(athena_info, dict) and athena_info:
            datasource_ids.append(_convert_legacy_athena_connection(owner["tenant_id"], module_name, athena_info, owner["id"]))

        payload = {
            "tenant_id": owner["tenant_id"],
            "name": module_name,
            "module_name": module_name,
            "description": "",
            "general_prompt": module_data.get("descricao_mestre") or "",
            "ai_service_id": default_ai_service_id,
            "datasource_ids": datasource_ids,
            "agents": [
                {
                    "name": agent_name,
                    "agent_type": "UserProxyAgent"
                    if (agent_data.get("type") or "").strip() in {"UserProxyAgent", "UserProxyGemini"}
                    else "AssistantAgent",
                    "prompt": agent_data.get("prompt") or "",
                    "tools": agent_data.get("tools") or [],
                    "allowed_interactions": agent_data.get("allowed_interactions") or [],
                    "sort_order": index,
                }
                for index, (agent_name, agent_data) in enumerate((module_data.get("submodules") or {}).items())
            ],
        }
        created = save_template_version(payload, current_user)
        deploy_template_version(created["template_id"], created["id"], current_user)
