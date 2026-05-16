import json
from pathlib import Path
from typing import Any, Dict, Optional

import psycopg2
import redis
from psycopg2.extras import RealDictCursor
from psycopg2.extras import Json

import config as settings


TEMPLATE_CACHE_PREFIX = "agent:templates"


def _redis_client() -> redis.Redis:
    return redis.Redis(
        host=settings.REDIS_HOST,
        port=settings.REDIS_PORT,
        decode_responses=True,
        ssl=bool(settings.REDIS_SSL),
    )


def _db_connection():
    return psycopg2.connect(
        host=settings.RDS_HOST,
        port=settings.RDS_PORT,
        dbname=settings.RDS_DB,
        user=settings.RDS_USER,
        password=settings.RDS_PASSWORD,
        cursor_factory=RealDictCursor,
    )


def _active_template_key(tenant_key: str) -> str:
    return f"{TEMPLATE_CACHE_PREFIX}:tenant:{tenant_key}:active"


def _build_ai_service_payload(row: Optional[dict]) -> Optional[Dict[str, Any]]:
    if not row:
        return None
    return {
        "id": row["id"],
        "provider": row["provider"],
        "name": row["name"],
        "model_name": row.get("model_name") or "",
        "tenant_id": row.get("tenant_id"),
        "config": row.get("config_json") or {},
        "secret": row.get("secret_json") or {},
    }


def _load_active_template_metadata(tenant_key: str) -> Optional[Dict[str, Any]]:
    try:
        with _db_connection() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    d.id AS deployment_id,
                    d.template_id,
                    d.template_version_id,
                    t.module_name,
                    v.ai_service_id,
                    s.id,
                    s.provider,
                    s.name,
                    s.model_name,
                    s.tenant_id,
                    s.config_json,
                    s.secret_json
                FROM agent_ui_template_deployments d
                JOIN agent_ui_templates t ON t.id = d.template_id
                LEFT JOIN agent_ui_template_versions v ON v.id = d.template_version_id
                LEFT JOIN agent_ui_ai_services s ON s.id = v.ai_service_id
                WHERE d.tenant_key = %s
                  AND d.is_active = TRUE
                ORDER BY d.deployed_at DESC
                LIMIT 1
                """,
                (tenant_key,),
            )
            row = cur.fetchone()
            if not row:
                return None

            ai_service = _build_ai_service_payload(row)
            cur.execute(
                """
                SELECT
                    ds.config_json,
                    ds.secret_json
                FROM agent_ui_template_version_datasources tvd
                JOIN agent_ui_template_versions v ON v.id = tvd.template_version_id
                JOIN agent_ui_datasources ds ON ds.id = tvd.datasource_id
                WHERE v.template_id = %s
                  AND ds.kind = 'athena'
                ORDER BY
                    CASE
                        WHEN COALESCE(ds.secret_json->>'aws_access_key_id', ds.config_json->>'aws_access_key_id', '') <> ''
                         AND COALESCE(ds.secret_json->>'aws_secret_access_key', ds.config_json->>'aws_secret_access_key', '') <> ''
                        THEN 1
                        ELSE 0
                    END DESC,
                    v.version_number DESC,
                    tvd.sort_order ASC
                LIMIT 1
                """,
                (row["template_id"],),
            )
            athena_row = cur.fetchone()
            athena_fallback = None
            if athena_row:
                config_json = athena_row.get("config_json") or {}
                secret_json = athena_row.get("secret_json") or {}
                athena_fallback = {
                    "database": config_json.get("database_name") or config_json.get("database") or "",
                    "output_location": config_json.get("output_location") or "",
                    "region_name": config_json.get("region_name") or "us-east-1",
                    "catalog_name": config_json.get("catalog_name") or "AwsDataCatalog",
                    "workgroup": config_json.get("workgroup") or "",
                    "aws_access_key_id": secret_json.get("aws_access_key_id") or config_json.get("aws_access_key_id") or "",
                    "aws_secret_access_key": secret_json.get("aws_secret_access_key") or config_json.get("aws_secret_access_key") or "",
                    "aws_session_token": secret_json.get("aws_session_token") or config_json.get("aws_session_token") or "",
                }
            if ai_service:
                return {
                    "deployment_id": row["deployment_id"],
                    "module_name": row["module_name"],
                    "template_id": row["template_id"],
                    "template_version_id": row["template_version_id"],
                    "ai_service": ai_service,
                    "athena_fallback": athena_fallback,
                }

            cur.execute(
                """
                SELECT
                    s.id,
                    s.provider,
                    s.name,
                    s.model_name,
                    s.tenant_id,
                    s.config_json,
                    s.secret_json
                FROM agent_ui_template_versions v
                JOIN agent_ui_ai_services s ON s.id = v.ai_service_id
                WHERE v.template_id = %s
                  AND v.ai_service_id IS NOT NULL
                ORDER BY v.version_number DESC
                LIMIT 1
                """,
                (row["template_id"],),
            )
            fallback_row = cur.fetchone()
            return {
                "deployment_id": row["deployment_id"],
                "module_name": row["module_name"],
                "template_id": row["template_id"],
                "template_version_id": row["template_version_id"],
                "ai_service": _build_ai_service_payload(fallback_row),
                "athena_fallback": athena_fallback,
            }
    except Exception:
        return None


def _choose_athena_datasource(datasources_catalog: list[dict]) -> Optional[dict]:
    athena_items = [
        item for item in (datasources_catalog or [])
        if isinstance(item, dict) and item.get("kind") == "athena"
    ]
    if not athena_items:
        return None

    def score(item: dict) -> tuple[int, int]:
        config = item.get("config") or {}
        secret = item.get("secret") or {}
        has_access = bool(secret.get("aws_access_key_id") or config.get("aws_access_key_id"))
        has_secret = bool(secret.get("aws_secret_access_key") or config.get("aws_secret_access_key"))
        has_output = bool(config.get("output_location"))
        return (int(has_access and has_secret), int(has_output))

    return sorted(athena_items, key=score, reverse=True)[0]


def _hydrate_module_payload(
    module_payload: dict,
    ai_service: Optional[Dict[str, Any]],
    athena_fallback: Optional[Dict[str, Any]],
) -> bool:
    changed = False

    if ai_service and not module_payload.get("ai_service"):
        module_payload["ai_service"] = ai_service
        changed = True

    athena_source = _choose_athena_datasource(module_payload.get("datasources_catalog") or [])
    if athena_source or athena_fallback:
        config = (athena_source or {}).get("config") or {}
        secret = (athena_source or {}).get("secret") or {}
        current = dict(module_payload.get("athena_connection") or {})
        fallback = athena_fallback or {}
        hydrated = {
            "database": current.get("database") or config.get("database_name") or config.get("database") or fallback.get("database") or "",
            "output_location": current.get("output_location") or config.get("output_location") or fallback.get("output_location") or "",
            "region_name": current.get("region_name") or config.get("region_name") or fallback.get("region_name") or "us-east-1",
            "catalog_name": current.get("catalog_name") or config.get("catalog_name") or fallback.get("catalog_name") or "AwsDataCatalog",
            "workgroup": current.get("workgroup") or config.get("workgroup") or fallback.get("workgroup") or "",
            "aws_access_key_id": (
                current.get("aws_access_key_id")
                or secret.get("aws_access_key_id")
                or config.get("aws_access_key_id")
                or fallback.get("aws_access_key_id")
                or ""
            ),
            "aws_secret_access_key": (
                current.get("aws_secret_access_key")
                or secret.get("aws_secret_access_key")
                or config.get("aws_secret_access_key")
                or fallback.get("aws_secret_access_key")
                or ""
            ),
            "aws_session_token": (
                current.get("aws_session_token")
                or secret.get("aws_session_token")
                or config.get("aws_session_token")
                or fallback.get("aws_session_token")
                or ""
            ),
        }
        if hydrated != current:
            module_payload["athena_connection"] = hydrated
            changed = True

    return changed


def _hydrate_compiled_template(
    compiled: Dict[str, dict],
    metadata: Optional[Dict[str, Any]],
) -> tuple[Dict[str, dict], bool]:
    if not isinstance(compiled, dict):
        return compiled, False

    changed = False
    target_module = (metadata or {}).get("module_name")
    ai_service = (metadata or {}).get("ai_service")
    athena_fallback = (metadata or {}).get("athena_fallback")

    for module_name, module_payload in compiled.items():
        if not isinstance(module_payload, dict):
            continue
        current_ai_service = ai_service if (not target_module or module_name == target_module) else None
        current_athena_fallback = athena_fallback if (not target_module or module_name == target_module) else None
        if _hydrate_module_payload(module_payload, current_ai_service, current_athena_fallback):
            changed = True

    return compiled, changed


def _persist_hydrated_template(tenant_key: str, metadata: Optional[Dict[str, Any]], compiled: Dict[str, dict]) -> None:
    payload = json.dumps(compiled, ensure_ascii=False)
    try:
        _redis_client().set(_active_template_key(tenant_key), payload)
    except Exception:
        pass

    deployment_id = (metadata or {}).get("deployment_id")
    if not deployment_id:
        return

    try:
        with _db_connection() as conn, conn.cursor() as cur:
            cur.execute(
                """
                UPDATE agent_ui_template_deployments
                SET compiled_json = %s
                WHERE id = %s
                """,
                (Json(compiled), deployment_id),
            )
    except Exception:
        pass


def _load_audit_template() -> Dict[str, dict]:
    base_dir = Path(__file__).resolve().parents[3]
    audit_path = base_dir / settings.AUDIT_MODULE_CONFIG
    if not audit_path.exists():
        return {}
    try:
        return json.loads(audit_path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def load_compiled_template_for_tenant(tenant_key: str) -> Optional[Dict[str, dict]]:
    tenant_key = (tenant_key or "").strip()
    if not tenant_key:
        return None

    metadata = _load_active_template_metadata(tenant_key)

    try:
        cached = _redis_client().get(_active_template_key(tenant_key))
        if cached:
            parsed = json.loads(cached)
            if isinstance(parsed, dict):
                hydrated, changed = _hydrate_compiled_template(parsed, metadata)
                if changed:
                    _persist_hydrated_template(tenant_key, metadata, hydrated)
                return hydrated
    except Exception:
        pass

    try:
        with _db_connection() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT compiled_json
                FROM agent_ui_template_deployments
                WHERE tenant_key = %s
                  AND is_active = TRUE
                ORDER BY deployed_at DESC
                LIMIT 1
                """,
                (tenant_key,),
            )
            row = cur.fetchone()
            if row and row.get("compiled_json"):
                compiled = row["compiled_json"]
                hydrated, changed = _hydrate_compiled_template(compiled, metadata)
                if changed:
                    _persist_hydrated_template(tenant_key, metadata, hydrated)
                else:
                    try:
                        _redis_client().set(_active_template_key(tenant_key), json.dumps(hydrated, ensure_ascii=False))
                    except Exception:
                        pass
                return hydrated
    except Exception:
        return None

    return None


def load_runtime_templates(tenant_key: str) -> Dict[str, dict]:
    compiled = load_compiled_template_for_tenant(tenant_key)
    if compiled:
        merged = dict(compiled)
        merged.update(_load_audit_template())
        return merged

    base_dir = Path(__file__).resolve().parents[3]
    main_path = base_dir / settings.AGENT_CONFIG
    combined: Dict[str, dict] = {}
    if main_path.exists():
        try:
            combined.update(json.loads(main_path.read_text(encoding="utf-8")))
        except Exception:
            pass
    combined.update(_load_audit_template())
    return combined
