import json
import re
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote

import redis
from psycopg2.extras import Json

from agent.ui.constants import ALLOWED_TYPES
from agent.ui.toolkit_loader import get_toolkits_with_functions
from ui.backend.core import config
from ui.backend.core.db import get_connection, new_id


SUPPORTED_TEMPLATE_AGENT_TYPES = list(ALLOWED_TYPES)
TEMPLATE_CACHE_PREFIX = "agent:templates"
LEGACY_TOOL_ALIASES = {}
LEGACY_AGENT_TYPE_ALIASES = {
    "baseagentopenai": "AssistantAgent",
    "baseopenaiagent": "AssistantAgent",
    "base_agent_openai": "AssistantAgent",
    "baseagentgemini": "AssistantAgent",
    "base_agent_gemini": "AssistantAgent",
    "baseagentgeminivision": "AssistantAgent",
    "base_agent_gemini_vision": "AssistantAgent",
    "userproxygemini": "UserProxyAgent",
    "user_proxy_gemini": "UserProxyAgent",
}


def slugify(value: str) -> str:
    normalized = (value or "").strip().lower()
    normalized = re.sub(r"[^a-z0-9]+", "_", normalized)
    return normalized.strip("_") or "template"


def ensure_agent_name(name: str) -> str:
    value = (name or "").strip()
    if not value:
        raise ValueError("O nome do agente é obrigatório.")
    if not value.endswith("_agent"):
        raise ValueError("O nome do agente deve terminar com '_agent'.")
    return value


def get_toolkit_catalog() -> Dict[str, Any]:
    raw = get_toolkits_with_functions()
    items = []
    flat_tools = []
    for toolkit_name, funcs in sorted(raw.items()):
        valid_funcs = [func for func in funcs if not str(func).startswith("Erro")]
        if not valid_funcs:
            continue
        tool_options = [f"{toolkit_name}.{func}" for func in valid_funcs]
        items.append(
            {
                "toolkit": toolkit_name,
                "functions": valid_funcs,
                "tools": tool_options,
            }
        )
        flat_tools.extend(tool_options)
    return {
        "agent_types": SUPPORTED_TEMPLATE_AGENT_TYPES,
        "toolkits": items,
        "tools": sorted(flat_tools),
    }


def normalize_tool_name(tool_name: str) -> str:
    return LEGACY_TOOL_ALIASES.get(tool_name, tool_name)


def normalize_tools_list(tool_names: List[str]) -> List[str]:
    normalized = []
    seen = set()
    for tool_name in tool_names or []:
        fixed_name = normalize_tool_name(tool_name)
        if fixed_name in seen:
            continue
        seen.add(fixed_name)
        normalized.append(fixed_name)
    return normalized


def normalize_agent_type(agent_type: str) -> str:
    value = (agent_type or "").strip()
    lowered = value.lower()
    if lowered in LEGACY_AGENT_TYPE_ALIASES:
        return LEGACY_AGENT_TYPE_ALIASES[lowered]
    if value in SUPPORTED_TEMPLATE_AGENT_TYPES:
        return value
    return value


def normalize_template_payload(payload: dict) -> dict:
    normalized = {**payload}
    normalized["datasource_ids"] = list(payload.get("datasource_ids") or [])
    normalized["agents"] = [
        {
            **agent,
            "agent_type": normalize_agent_type(agent.get("agent_type") or "AssistantAgent"),
            "tools": normalize_tools_list(agent.get("tools") or []),
            "allowed_interactions": list(agent.get("allowed_interactions") or []),
            "file_ids": list(agent.get("file_ids") or []),
            "secret_ids": list(agent.get("secret_ids") or []),
        }
        for agent in (payload.get("agents") or [])
    ]
    return normalized


def get_redis_client() -> redis.Redis:
    return redis.Redis(
        host=config.REDIS_HOST,
        port=config.REDIS_PORT,
        decode_responses=True,
        ssl=config.REDIS_SSL,
    )


def active_template_redis_key(tenant_key: str) -> str:
    return f"{TEMPLATE_CACHE_PREFIX}:tenant:{tenant_key}:active"


def version_template_redis_key(tenant_key: str, version_id: str) -> str:
    return f"{TEMPLATE_CACHE_PREFIX}:tenant:{tenant_key}:version:{version_id}"


def require_template_manager(current_user: dict) -> None:
    if current_user.get("role") == "master":
        return
    if not current_user.get("permissions", {}).get("templates", {}).get("view"):
        raise PermissionError("Usuario sem permissao nesse recurso")


def _load_datasource_rows(datasource_ids: List[str]) -> List[dict]:
    if not datasource_ids:
        return []
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT *
            FROM agent_ui_datasources
            WHERE id = ANY(%s)
            ORDER BY name
            """,
            (datasource_ids,),
        )
        return cur.fetchall()


def _load_file_rows(file_ids: List[str]) -> List[dict]:
    if not file_ids:
        return []
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT f.*, t.name AS tenant_name
            FROM agent_ui_files f
            LEFT JOIN agent_ui_tenants t ON t.id = f.tenant_id
            WHERE f.id = ANY(%s)
            ORDER BY f.name
            """,
            (file_ids,),
        )
        return cur.fetchall()


def _load_secret_rows(secret_ids: List[str]) -> List[dict]:
    if not secret_ids:
        return []
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT s.*, t.name AS tenant_name
            FROM agent_ui_secrets s
            LEFT JOIN agent_ui_tenants t ON t.id = s.tenant_id
            WHERE s.id = ANY(%s)
            ORDER BY s.name
            """,
            (secret_ids,),
        )
        return cur.fetchall()


def _load_ai_service_row(ai_service_id: Optional[str]) -> Optional[dict]:
    if not ai_service_id:
        return None
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT s.*, t.name AS tenant_name
            FROM agent_ui_ai_services s
            LEFT JOIN agent_ui_tenants t ON t.id = s.tenant_id
            WHERE s.id = %s
            LIMIT 1
            """,
            (ai_service_id,),
        )
        return cur.fetchone()


def _build_runtime_uri(kind: str, config_json: Dict[str, Any], secret_json: Dict[str, Any]) -> Optional[str]:
    host = config_json.get("host") or ""
    port = config_json.get("port")
    database_name = config_json.get("database_name") or ""
    username = config_json.get("username") or ""
    password = secret_json.get("password") or ""
    ssl_mode = config_json.get("ssl_mode") or ""

    if kind == "sqlite":
        sqlite_mode = config_json.get("sqlite_mode") or "path"
        if sqlite_mode == "path" and config_json.get("sqlite_path"):
            path = config_json["sqlite_path"]
            if path == ":memory:":
                return "sqlite:///:memory:"
            clean_path = path if path.startswith("/") else f"/{path}"
            return f"sqlite://{clean_path}"
        return None

    if kind == "postgresql":
        return (
            f"postgresql://{quote(username)}:{quote(password)}@{host}:{port}/{database_name}"
            + (f"?sslmode={quote(ssl_mode)}" if ssl_mode else "")
        )

    if kind in {"mysql", "mariadb"}:
        return f"mysql+pymysql://{quote(username)}:{quote(password)}@{host}:{port}/{database_name}"

    if kind == "sqlserver":
        return f"mssql+pytds://{quote(username)}:{quote(password)}@{host}:{port}/{database_name}"

    return None


def _runtime_datasource_payload(row: dict) -> Dict[str, Any]:
    config_json = row.get("config_json") or {}
    secret_json = row.get("secret_json") or {}
    return {
        "id": row["id"],
        "name": row["name"],
        "kind": row["kind"],
        "description": row.get("description") or "",
        "config": config_json,
        "secret": secret_json,
        "runtime_uri": _build_runtime_uri(row["kind"], config_json, secret_json),
    }


def _compile_template_json(
    template_row: dict,
    version_row: dict,
    agents: List[dict],
    datasource_rows: List[dict],
    ai_service_row: Optional[dict],
) -> Dict[str, Any]:
    module_name = template_row["module_name"]
    compiled_agents = {}
    known_agent_names = {agent["name"] for agent in agents}

    for agent in agents:
        allowed_interactions = [
            item["target_agent_name"]
            for item in sorted(agent["interactions"], key=lambda x: (x["sort_order"], x["target_agent_name"]))
            if item["target_agent_name"] in known_agent_names
        ]
        compiled_agents[agent["name"]] = {
            "type": normalize_agent_type(agent["agent_type"]),
            "tools": [tool["tool_name"] for tool in sorted(agent["tools"], key=lambda x: (x["sort_order"], x["tool_name"]))],
            "prompt": agent["prompt"] or "",
            "rag_files": [item.get("file_url") or "" for item in sorted(agent.get("files", []), key=lambda x: (x["sort_order"], x["name"])) if item.get("file_url")],
            "linked_files": [
                {
                    "id": item["id"],
                    "name": item["name"],
                    "url": item.get("file_url") or "",
                    "original_filename": item.get("original_filename") or "",
                }
                for item in sorted(agent.get("files", []), key=lambda x: (x["sort_order"], x["name"]))
            ],
            "linked_secrets": [
                {
                    "id": item["id"],
                    "name": item["name"],
                    "value": item.get("secret_value") or "",
                    "description": item.get("description") or "",
                }
                for item in sorted(agent.get("secrets", []), key=lambda x: (x["sort_order"], x["name"]))
            ],
            "allowed_interactions": allowed_interactions,
        }

    db_connections = {}
    athena_connection = None
    datasources_catalog = []

    for datasource in datasource_rows:
        runtime = _runtime_datasource_payload(datasource)
        datasources_catalog.append(runtime)
        if runtime["runtime_uri"]:
            alias = slugify(datasource["name"])
            db_connections[alias] = {
                "description": datasource["description"] or datasource["name"],
                "uri": runtime["runtime_uri"],
            }
        if runtime["kind"] == "athena" and athena_connection is None:
            athena_connection = {
                "database": runtime["config"].get("database_name") or runtime["config"].get("database") or "",
                "output_location": runtime["config"].get("output_location") or "",
                "region_name": runtime["config"].get("region_name") or "us-east-1",
                "catalog_name": runtime["config"].get("catalog_name") or "AwsDataCatalog",
                "workgroup": runtime["config"].get("workgroup") or "",
                "aws_access_key_id": runtime["secret"].get("aws_access_key_id") or "",
                "aws_secret_access_key": runtime["secret"].get("aws_secret_access_key") or "",
                "aws_session_token": runtime["secret"].get("aws_session_token") or "",
            }

    module_payload = {
        "submodules": compiled_agents,
        "DB_connections": db_connections,
        "descricao_mestre": version_row["general_prompt"] or "",
        "datasources_catalog": datasources_catalog,
    }
    if athena_connection:
        module_payload["athena_connection"] = athena_connection
    if ai_service_row:
        module_payload["ai_service"] = {
            "id": ai_service_row["id"],
            "provider": ai_service_row["provider"],
            "name": ai_service_row["name"],
            "model_name": ai_service_row.get("model_name") or "",
            "tenant_id": ai_service_row["tenant_id"],
            "config": ai_service_row.get("config_json") or {},
            "secret": ai_service_row.get("secret_json") or {},
        }

    return {module_name: module_payload}


def _validate_template_payload(payload: dict, tool_catalog: Dict[str, Any]) -> None:
    name = (payload.get("name") or "").strip()
    module_name = (payload.get("module_name") or "").strip()
    ai_service_id = (payload.get("ai_service_id") or "").strip()
    agents = payload.get("agents") or []

    if not name:
        raise ValueError("O nome do template é obrigatório.")
    if not module_name:
        raise ValueError("O nome do módulo é obrigatório.")
    if not ai_service_id:
        raise ValueError("Selecione um servico de IA para o template.")
    if not agents:
        raise ValueError("O template precisa ter ao menos um agente.")

    valid_types = set(tool_catalog["agent_types"])
    valid_tools = set(tool_catalog["tools"])
    seen_names = set()

    for agent in agents:
        agent_name = ensure_agent_name(agent.get("name"))
        if agent_name in seen_names:
            raise ValueError(f"Agente duplicado no template: {agent_name}")
        seen_names.add(agent_name)

        if normalize_agent_type(agent.get("agent_type")) not in valid_types:
            raise ValueError(f"Tipo de agente inválido para {agent_name}.")

        for tool_name in agent.get("tools") or []:
            if tool_name not in valid_tools:
                raise ValueError(f"Toolkit inválido para {agent_name}: {tool_name}")

    for agent in agents:
        agent_name = agent["name"]
        for target_name in agent.get("allowed_interactions") or []:
            if target_name not in seen_names:
                raise ValueError(f"{agent_name} referencia interação inválida: {target_name}")


def _serialize_template_row(row: dict) -> dict:
    return {
        "id": row["id"],
        "tenant_id": row["tenant_id"],
        "tenant_name": row.get("tenant_name"),
        "tenant_key": row.get("tenant_key"),
        "name": row["name"],
        "module_name": row["module_name"],
        "description": row.get("description") or "",
        "is_active": row.get("is_active", True),
        "active_version_id": row.get("active_version_id"),
        "active_version_number": row.get("active_version_number"),
        "active_deployed_at": row.get("active_deployed_at"),
        "versions_count": row.get("versions_count", 0),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
    }


def _serialize_version_payload(template_row: dict, version_row: dict, agents: List[dict], datasource_rows: List[dict]) -> dict:
    return {
        "id": version_row["id"],
        "template_id": version_row["template_id"],
        "tenant_id": version_row["tenant_id"],
        "version_number": version_row["version_number"],
        "general_prompt": version_row["general_prompt"] or "",
        "ai_service_id": version_row.get("ai_service_id"),
        "created_at": version_row["created_at"],
        "based_on_version_id": version_row.get("based_on_version_id"),
        "template": {
            "name": template_row["name"],
            "module_name": template_row["module_name"],
            "description": template_row.get("description") or "",
        },
        "agents": [
            {
                "id": agent["id"],
                "name": agent["name"],
                "agent_type": normalize_agent_type(agent["agent_type"]),
                "prompt": agent["prompt"] or "",
                "sort_order": agent["sort_order"],
                "tools": normalize_tools_list([tool["tool_name"] for tool in sorted(agent["tools"], key=lambda x: (x["sort_order"], x["tool_name"]))]),
                "allowed_interactions": [item["target_agent_name"] for item in sorted(agent["interactions"], key=lambda x: (x["sort_order"], x["target_agent_name"]))],
                "file_ids": [item["id"] for item in sorted(agent.get("files", []), key=lambda x: (x["sort_order"], x["name"]))],
                "secret_ids": [item["id"] for item in sorted(agent.get("secrets", []), key=lambda x: (x["sort_order"], x["name"]))],
            }
            for agent in sorted(agents, key=lambda x: (x["sort_order"], x["name"]))
        ],
        "datasource_ids": [row["id"] for row in datasource_rows],
        "datasources": [
            {
                "id": row["id"],
                "name": row["name"],
                "kind": row["kind"],
                "summary": row.get("summary"),
                "tenant_name": row.get("tenant_name"),
            }
            for row in datasource_rows
        ],
        "ai_service": version_row.get("ai_service"),
        "compiled_json": version_row.get("compiled_json"),
    }


def list_templates(current_user: dict, include_inactive: bool = False) -> List[dict]:
    with get_connection() as conn, conn.cursor() as cur:
        if current_user["role"] == "master":
            cur.execute(
                """
                SELECT
                    t.*,
                    ten.name AS tenant_name,
                    ten.tenant_key,
                    COUNT(v.id) AS versions_count,
                    active.template_version_id AS active_version_id,
                    av.version_number AS active_version_number,
                    active.deployed_at AS active_deployed_at
                FROM agent_ui_templates t
                JOIN agent_ui_tenants ten ON ten.id = t.tenant_id
                LEFT JOIN agent_ui_template_versions v ON v.template_id = t.id
                LEFT JOIN agent_ui_template_deployments active
                    ON active.template_id = t.id
                   AND active.is_active = TRUE
                LEFT JOIN agent_ui_template_versions av ON av.id = active.template_version_id
                WHERE t.is_deleted = FALSE
                  AND (%s = TRUE OR t.is_active = TRUE)
                GROUP BY t.id, ten.name, ten.tenant_key, active.template_version_id, av.version_number, active.deployed_at
                ORDER BY t.updated_at DESC, t.name ASC
                """,
                (include_inactive,),
            )
        else:
            cur.execute(
                """
                SELECT
                    t.*,
                    ten.name AS tenant_name,
                    ten.tenant_key,
                    COUNT(v.id) AS versions_count,
                    active.template_version_id AS active_version_id,
                    av.version_number AS active_version_number,
                    active.deployed_at AS active_deployed_at
                FROM agent_ui_templates t
                JOIN agent_ui_tenants ten ON ten.id = t.tenant_id
                LEFT JOIN agent_ui_template_versions v ON v.template_id = t.id
                LEFT JOIN agent_ui_template_deployments active
                    ON active.template_id = t.id
                   AND active.is_active = TRUE
                LEFT JOIN agent_ui_template_versions av ON av.id = active.template_version_id
                WHERE t.is_deleted = FALSE
                  AND t.tenant_id = %s
                  AND (%s = TRUE OR t.is_active = TRUE)
                GROUP BY t.id, ten.name, ten.tenant_key, active.template_version_id, av.version_number, active.deployed_at
                ORDER BY t.updated_at DESC, t.name ASC
                """,
                (current_user["tenant_id"], include_inactive),
            )
        return [_serialize_template_row(row) for row in cur.fetchall()]


def get_template_detail(template_id: str, current_user: dict) -> dict:
    with get_connection() as conn, conn.cursor() as cur:
        if current_user["role"] == "master":
            cur.execute(
                """
                SELECT t.*, ten.name AS tenant_name, ten.tenant_key
                FROM agent_ui_templates t
                JOIN agent_ui_tenants ten ON ten.id = t.tenant_id
                WHERE t.id = %s AND t.is_deleted = FALSE
                LIMIT 1
                """,
                (template_id,),
            )
        else:
            cur.execute(
                """
                SELECT t.*, ten.name AS tenant_name, ten.tenant_key
                FROM agent_ui_templates t
                JOIN agent_ui_tenants ten ON ten.id = t.tenant_id
                WHERE t.id = %s AND t.tenant_id = %s AND t.is_deleted = FALSE
                LIMIT 1
                """,
                (template_id, current_user["tenant_id"]),
            )
        template_row = cur.fetchone()
        if not template_row:
            raise KeyError("Template não encontrado.")

        cur.execute(
            """
            SELECT
                v.*,
                CASE WHEN d.is_active THEN TRUE ELSE FALSE END AS is_active
            FROM agent_ui_template_versions v
            LEFT JOIN agent_ui_template_deployments d
                ON d.template_version_id = v.id
               AND d.is_active = TRUE
            WHERE v.template_id = %s
            ORDER BY v.version_number DESC
            """,
            (template_id,),
        )
        versions = cur.fetchall()

    return {
        "template": _serialize_template_row(template_row),
        "versions": [
            {
                "id": row["id"],
                "version_number": row["version_number"],
                "created_at": row["created_at"],
                "is_active": bool(row.get("is_active")),
            }
            for row in versions
        ],
    }


def get_version_payload(version_id: str, current_user: dict) -> dict:
    with get_connection() as conn, conn.cursor() as cur:
        if current_user["role"] == "master":
            cur.execute(
                """
                SELECT v.*, t.name, t.module_name, t.description, t.tenant_id
                FROM agent_ui_template_versions v
                JOIN agent_ui_templates t ON t.id = v.template_id
                WHERE v.id = %s AND t.is_deleted = FALSE
                LIMIT 1
                """,
                (version_id,),
            )
        else:
            cur.execute(
                """
                SELECT v.*, t.name, t.module_name, t.description, t.tenant_id
                FROM agent_ui_template_versions v
                JOIN agent_ui_templates t ON t.id = v.template_id
                WHERE v.id = %s AND t.tenant_id = %s AND t.is_deleted = FALSE
                LIMIT 1
                """,
                (version_id, current_user["tenant_id"]),
            )
        version_row = cur.fetchone()
        if not version_row:
            raise KeyError("Versão do template não encontrada.")

        template_row = {
            "id": version_row["template_id"],
            "tenant_id": version_row["tenant_id"],
            "name": version_row["name"],
            "module_name": version_row["module_name"],
            "description": version_row["description"],
        }

        cur.execute(
            """
            SELECT *
            FROM agent_ui_template_version_agents
            WHERE template_version_id = %s
            ORDER BY sort_order, name
            """,
            (version_id,),
        )
        agent_rows = cur.fetchall()

        agents = []
        for agent_row in agent_rows:
            cur.execute(
                """
                SELECT *
                FROM agent_ui_template_version_agent_tools
                WHERE agent_id = %s
                ORDER BY sort_order, tool_name
                """,
                (agent_row["id"],),
            )
            tools = cur.fetchall()
            cur.execute(
                """
                SELECT *
                FROM agent_ui_template_version_agent_interactions
                WHERE agent_id = %s
                ORDER BY sort_order, target_agent_name
                """,
                (agent_row["id"],),
            )
            interactions = cur.fetchall()
            cur.execute(
                """
                SELECT f.*, link.sort_order
                FROM agent_ui_template_version_agent_files link
                JOIN agent_ui_files f ON f.id = link.file_id
                WHERE link.agent_id = %s
                ORDER BY link.sort_order, f.name
                """,
                (agent_row["id"],),
            )
            files = cur.fetchall()
            cur.execute(
                """
                SELECT s.*, link.sort_order
                FROM agent_ui_template_version_agent_secrets link
                JOIN agent_ui_secrets s ON s.id = link.secret_id
                WHERE link.agent_id = %s
                ORDER BY link.sort_order, s.name
                """,
                (agent_row["id"],),
            )
            secrets = cur.fetchall()
            enriched = dict(agent_row)
            enriched["tools"] = tools
            enriched["interactions"] = interactions
            enriched["files"] = files
            enriched["secrets"] = secrets
            agents.append(enriched)

        cur.execute(
            """
            SELECT d.*, ten.name AS tenant_name
            FROM agent_ui_template_version_datasources tvd
            JOIN agent_ui_datasources d ON d.id = tvd.datasource_id
            LEFT JOIN agent_ui_tenants ten ON ten.id = d.tenant_id
            WHERE tvd.template_version_id = %s
            ORDER BY tvd.sort_order, d.name
            """,
            (version_id,),
        )
        datasource_rows = cur.fetchall()
        ai_service_row = _load_ai_service_row(version_row.get("ai_service_id"))

    for row in datasource_rows:
        row["summary"] = f"{row['kind']} - {row['name']}"

    if ai_service_row:
        version_row["ai_service"] = {
            "id": ai_service_row["id"],
            "tenant_id": ai_service_row["tenant_id"],
            "tenant_name": ai_service_row.get("tenant_name"),
            "provider": ai_service_row["provider"],
            "name": ai_service_row["name"],
            "description": ai_service_row.get("description") or "",
            "model_name": ai_service_row.get("model_name") or "",
            "is_active": ai_service_row.get("is_active", True),
        }

    return _serialize_version_payload(template_row, version_row, agents, datasource_rows)


def _resolve_template_version_for_runtime(template_id: str, version_id: Optional[str], current_user: dict) -> Tuple[dict, dict]:
    with get_connection() as conn, conn.cursor() as cur:
        if current_user["role"] == "master":
            cur.execute(
                """
                SELECT t.*, ten.tenant_key, ten.name AS tenant_name
                FROM agent_ui_templates t
                JOIN agent_ui_tenants ten ON ten.id = t.tenant_id
                WHERE t.id = %s AND t.is_deleted = FALSE
                LIMIT 1
                """,
                (template_id,),
            )
        else:
            cur.execute(
                """
                SELECT t.*, ten.tenant_key, ten.name AS tenant_name
                FROM agent_ui_templates t
                JOIN agent_ui_tenants ten ON ten.id = t.tenant_id
                WHERE t.id = %s AND t.tenant_id = %s AND t.is_deleted = FALSE
                LIMIT 1
                """,
                (template_id, current_user["tenant_id"]),
            )
        template_row = cur.fetchone()
        if not template_row:
            raise KeyError("Template não encontrado.")

        if version_id:
            version_payload = get_version_payload(version_id, current_user)
        else:
            cur.execute(
                """
                SELECT id
                FROM agent_ui_template_versions
                WHERE template_id = %s
                ORDER BY version_number DESC
                LIMIT 1
                """,
                (template_id,),
            )
            latest_version = cur.fetchone()
            if not latest_version:
                raise ValueError("O template ainda nao possui versoes salvas.")
            version_payload = get_version_payload(latest_version["id"], current_user)

    if version_payload["template_id"] != template_id:
        raise ValueError("A versão selecionada não pertence ao template informado.")
    if version_payload["tenant_id"] != template_row["tenant_id"]:
        raise ValueError("A versão selecionada pertence a outro tenant.")
    return template_row, version_payload


def _compile_version_payload_for_runtime(template_row: dict, version_payload: dict) -> Dict[str, Any]:
    datasource_rows = _load_datasource_rows(version_payload["datasource_ids"])
    all_file_ids = []
    all_secret_ids = []
    for item in version_payload["agents"]:
        all_file_ids.extend(item.get("file_ids") or [])
        all_secret_ids.extend(item.get("secret_ids") or [])
    file_rows = _load_file_rows(all_file_ids)
    secret_rows = _load_secret_rows(all_secret_ids)
    ai_service_row = _load_ai_service_row(version_payload.get("ai_service_id"))
    datasource_map = {row["id"]: row for row in datasource_rows}
    file_map = {row["id"]: row for row in file_rows}
    secret_map = {row["id"]: row for row in secret_rows}
    ordered_datasources = [datasource_map[data_id] for data_id in version_payload["datasource_ids"] if data_id in datasource_map]

    agent_rows = []
    for item in version_payload["agents"]:
        agent_rows.append(
            {
                "name": item["name"],
                "agent_type": normalize_agent_type(item["agent_type"]),
                "prompt": item["prompt"],
                "sort_order": item["sort_order"],
                "tools": [{"tool_name": tool_name, "sort_order": idx} for idx, tool_name in enumerate(item["tools"])],
                "interactions": [{"target_agent_name": target, "sort_order": idx} for idx, target in enumerate(item["allowed_interactions"])],
                "files": [{**file_map[file_id], "sort_order": idx} for idx, file_id in enumerate(item.get("file_ids") or []) if file_id in file_map],
                "secrets": [{**secret_map[secret_id], "sort_order": idx} for idx, secret_id in enumerate(item.get("secret_ids") or []) if secret_id in secret_map],
            }
        )

    version_row = {
        "id": version_payload["id"],
        "template_id": version_payload["template_id"],
        "tenant_id": version_payload["tenant_id"],
        "version_number": version_payload["version_number"],
        "general_prompt": version_payload["general_prompt"],
    }
    return _compile_template_json(template_row, version_row, agent_rows, ordered_datasources, ai_service_row)


def _next_version_number(cur, template_id: str) -> int:
    cur.execute(
        """
        SELECT COALESCE(MAX(version_number), 0) + 1 AS next_version
        FROM agent_ui_template_versions
        WHERE template_id = %s
        """,
        (template_id,),
    )
    return cur.fetchone()["next_version"]


def save_template_version(payload: dict, current_user: dict, template_id: Optional[str] = None, based_on_version_id: Optional[str] = None) -> dict:
    require_template_manager(current_user)
    payload = normalize_template_payload(payload)
    tool_catalog = get_toolkit_catalog()
    _validate_template_payload(payload, tool_catalog)

    tenant_id = payload.get("tenant_id") or current_user["tenant_id"]
    ai_service_id = (payload.get("ai_service_id") or "").strip()
    if current_user["role"] != "master":
        tenant_id = current_user["tenant_id"]

    with get_connection() as conn, conn.cursor() as cur:
        if template_id:
            cur.execute(
                """
                SELECT *
                FROM agent_ui_templates
                WHERE id = %s AND is_deleted = FALSE
                LIMIT 1
                """,
                (template_id,),
            )
            template_row = cur.fetchone()
            if not template_row:
                raise KeyError("Template não encontrado.")
        else:
            module_name = (payload.get("module_name") or "").strip()
            cur.execute(
                """
                SELECT id
                FROM agent_ui_templates
                WHERE tenant_id = %s AND module_name = %s AND is_deleted = FALSE
                LIMIT 1
                """,
                (tenant_id, module_name),
            )
            if cur.fetchone():
                raise ValueError("Já existe um template com esse nome de módulo para o tenant.")

            template_id = new_id()
            cur.execute(
                """
                INSERT INTO agent_ui_templates (
                    id, tenant_id, name, module_name, description, is_active, created_by
                )
                VALUES (%s, %s, %s, %s, %s, TRUE, %s)
                RETURNING *
                """,
                (
                    template_id,
                    tenant_id,
                    payload["name"].strip(),
                    payload["module_name"].strip(),
                    payload.get("description", "").strip(),
                    current_user["id"],
                ),
            )
            template_row = cur.fetchone()

        if ai_service_id:
            cur.execute(
                """
                SELECT *
                FROM agent_ui_ai_services
                WHERE id = %s
                  AND tenant_id = %s
                LIMIT 1
                """,
                (ai_service_id, tenant_id),
            )
            ai_service_row = cur.fetchone()
            if not ai_service_row:
                raise ValueError("O servico de IA selecionado nao pertence ao tenant informado.")
        else:
            ai_service_row = None

        version_id = new_id()
        version_number = _next_version_number(cur, template_id)

        cur.execute(
            """
            INSERT INTO agent_ui_template_versions (
                id, template_id, tenant_id, version_number, general_prompt, ai_service_id, source_snapshot,
                based_on_version_id, created_by
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING *
            """,
            (
                version_id,
                template_id,
                tenant_id,
                version_number,
                payload.get("general_prompt", ""),
                ai_service_row["id"] if ai_service_row else None,
                Json(payload),
                based_on_version_id,
                current_user["id"],
            ),
        )

        cur.execute(
            """
            UPDATE agent_ui_templates
            SET name = %s,
                module_name = %s,
                description = %s,
                is_active = TRUE,
                updated_at = NOW()
            WHERE id = %s
            """,
            (
                payload["name"].strip(),
                payload["module_name"].strip(),
                payload.get("description", "").strip(),
                template_id,
            ),
        )

        for index, agent in enumerate(payload.get("agents") or []):
            agent_id = new_id()
            cur.execute(
                """
                INSERT INTO agent_ui_template_version_agents (
                    id, template_version_id, name, agent_type, prompt, sort_order
                )
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (
                    agent_id,
                    version_id,
                    ensure_agent_name(agent["name"]),
                    normalize_agent_type(agent["agent_type"]),
                    agent.get("prompt", ""),
                    index,
                ),
            )

            for tool_index, tool_name in enumerate(agent.get("tools") or []):
                cur.execute(
                    """
                    INSERT INTO agent_ui_template_version_agent_tools (
                        id, agent_id, tool_name, sort_order
                    )
                    VALUES (%s, %s, %s, %s)
                    """,
                    (new_id(), agent_id, tool_name, tool_index),
                )

            for interaction_index, target_name in enumerate(agent.get("allowed_interactions") or []):
                cur.execute(
                    """
                    INSERT INTO agent_ui_template_version_agent_interactions (
                        id, agent_id, target_agent_name, sort_order
                    )
                    VALUES (%s, %s, %s, %s)
                    """,
                    (new_id(), agent_id, target_name, interaction_index),
                )

            for file_index, file_id in enumerate(agent.get("file_ids") or []):
                cur.execute(
                    """
                    INSERT INTO agent_ui_template_version_agent_files (
                        id, agent_id, file_id, sort_order
                    )
                    VALUES (%s, %s, %s, %s)
                    """,
                    (new_id(), agent_id, file_id, file_index),
                )

            for secret_index, secret_id in enumerate(agent.get("secret_ids") or []):
                cur.execute(
                    """
                    INSERT INTO agent_ui_template_version_agent_secrets (
                        id, agent_id, secret_id, sort_order
                    )
                    VALUES (%s, %s, %s, %s)
                    """,
                    (new_id(), agent_id, secret_id, secret_index),
                )

        for index, datasource_id in enumerate(payload.get("datasource_ids") or []):
            cur.execute(
                """
                INSERT INTO agent_ui_template_version_datasources (
                    id, template_version_id, datasource_id, sort_order
                )
                VALUES (%s, %s, %s, %s)
                """,
                (new_id(), version_id, datasource_id, index),
            )

    return get_version_payload(version_id, current_user)


def delete_template(template_id: str, current_user: dict) -> None:
    require_template_manager(current_user)
    with get_connection() as conn, conn.cursor() as cur:
        if current_user["role"] == "master":
            cur.execute(
                "UPDATE agent_ui_templates SET is_deleted = TRUE, updated_at = NOW() WHERE id = %s",
                (template_id,),
            )
        else:
            cur.execute(
                "UPDATE agent_ui_templates SET is_deleted = TRUE, updated_at = NOW() WHERE id = %s AND tenant_id = %s",
                (template_id, current_user["tenant_id"]),
            )
        if cur.rowcount == 0:
            raise KeyError("Template não encontrado.")
        cur.execute(
            """
            UPDATE agent_ui_template_deployments
            SET is_active = FALSE
            WHERE template_id = %s AND is_active = TRUE
            """,
            (template_id,),
        )


def set_template_active(template_id: str, is_active: bool, current_user: dict) -> None:
    require_template_manager(current_user)
    with get_connection() as conn, conn.cursor() as cur:
        if not is_active:
            if current_user["role"] == "master":
                cur.execute(
                    """
                    SELECT 1
                    FROM agent_ui_template_deployments
                    WHERE template_id = %s
                      AND is_active = TRUE
                    LIMIT 1
                    """,
                    (template_id,),
                )
            else:
                cur.execute(
                    """
                    SELECT 1
                    FROM agent_ui_template_deployments d
                    JOIN agent_ui_templates t ON t.id = d.template_id
                    WHERE d.template_id = %s
                      AND d.is_active = TRUE
                      AND t.tenant_id = %s
                    LIMIT 1
                    """,
                    (template_id, current_user["tenant_id"]),
                )
            if cur.fetchone():
                raise ValueError("Não é permitido inativar um template que está deployado.")

        if current_user["role"] == "master":
            cur.execute(
                """
                UPDATE agent_ui_templates
                SET is_active = %s,
                    updated_at = NOW()
                WHERE id = %s AND is_deleted = FALSE
                """,
                (is_active, template_id),
            )
        else:
            cur.execute(
                """
                UPDATE agent_ui_templates
                SET is_active = %s,
                    updated_at = NOW()
                WHERE id = %s
                  AND tenant_id = %s
                  AND is_deleted = FALSE
                """,
                (is_active, template_id, current_user["tenant_id"]),
            )
        if cur.rowcount == 0:
            raise KeyError("Template não encontrado.")


def deploy_template_version(template_id: str, version_id: str, current_user: dict) -> dict:
    require_template_manager(current_user)
    template_row, version_payload = _resolve_template_version_for_runtime(template_id, version_id, current_user)
    if not template_row.get("tenant_key"):
        raise ValueError("O tenant precisa ter um tenant_key configurado para fazer deploy.")
    compiled_json = _compile_version_payload_for_runtime(template_row, version_payload)
    redis_key = active_template_redis_key(template_row["tenant_key"])

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            UPDATE agent_ui_template_versions
            SET compiled_json = %s,
                validation_errors = NULL
            WHERE id = %s
            """,
            (Json(compiled_json), version_id),
        )
        cur.execute(
            """
            UPDATE agent_ui_template_deployments
            SET is_active = FALSE
            WHERE tenant_id = %s AND is_active = TRUE
            """,
            (template_row["tenant_id"],),
        )
        deployment_id = new_id()
        cur.execute(
            """
            INSERT INTO agent_ui_template_deployments (
                id, tenant_id, tenant_key, template_id, template_version_id,
                compiled_json, redis_key, deployed_by, is_active
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, TRUE)
            RETURNING *
            """,
            (
                deployment_id,
                template_row["tenant_id"],
                template_row["tenant_key"],
                template_id,
                version_id,
                Json(compiled_json),
                redis_key,
                current_user["id"],
            ),
        )
        deployment_row = cur.fetchone()

    redis_client = get_redis_client()
    payload_text = json.dumps(compiled_json, ensure_ascii=False)
    version_pattern = f"{TEMPLATE_CACHE_PREFIX}:tenant:{template_row['tenant_key']}:version:*"
    try:
        old_version_keys = list(redis_client.scan_iter(match=version_pattern))
        if old_version_keys:
            redis_client.delete(*old_version_keys)
    except Exception:
        pass
    redis_client.set(redis_key, payload_text)

    return {
        "deployment_id": deployment_row["id"],
        "tenant_id": template_row["tenant_id"],
        "tenant_key": template_row["tenant_key"],
        "template_id": template_id,
        "template_name": template_row["name"],
        "template_version_id": version_id,
        "compiled_json": compiled_json,
        "redis_key": redis_key,
    }


def export_template_json(template_id: str, current_user: dict, version_id: Optional[str] = None) -> Tuple[str, Dict[str, Any]]:
    template_row, version_payload = _resolve_template_version_for_runtime(template_id, version_id, current_user)
    compiled_json = _compile_version_payload_for_runtime(template_row, version_payload)
    filename = f"{slugify(template_row['name'])}_v{version_payload['version_number']}.json"
    return filename, compiled_json


