import json
import os
import sqlite3
import tempfile
import time
from typing import Any, Dict, Tuple

import boto3
import httpx
import psycopg2
import pymysql
import pytds
from google.cloud import bigquery
from google.oauth2 import service_account


SUPPORTED_DATASOURCE_KINDS = {
    "postgresql",
    "mysql",
    "mariadb",
    "sqlserver",
    "sqlite",
    "athena",
    "bigquery",
}


def _clean(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _normalize_kind(raw_kind: str) -> str:
    value = _clean(raw_kind).lower()
    aliases = {
        "postgres": "postgresql",
        "postgresql": "postgresql",
        "mysql": "mysql",
        "mariadb": "mariadb",
        "sqlserver": "sqlserver",
        "sql_server": "sqlserver",
        "mssql": "sqlserver",
        "sqlite": "sqlite",
        "athena": "athena",
        "bigquery": "bigquery",
        "big_query": "bigquery",
        "bq": "bigquery",
    }
    return aliases.get(value, value)


def _to_int(value: Any, default: int | None = None) -> int | None:
    if value in (None, ""):
        return default
    return int(value)


def _parse_service_account_json(raw_json: str) -> Dict[str, Any]:
    try:
        parsed = json.loads(raw_json)
    except json.JSONDecodeError as error:
        raise ValueError(f"JSON de service account invalido: {error}") from error
    if not isinstance(parsed, dict):
        raise ValueError("O JSON de service account precisa ser um objeto.")
    return parsed


def _mask_secret(secret_value: str) -> str:
    if not secret_value:
        return ""
    if len(secret_value) <= 6:
        return "*" * len(secret_value)
    return f"{secret_value[:3]}***{secret_value[-3:]}"


def require_datasource_manager(current_user: dict) -> None:
    if current_user.get("role") == "master":
        return
    if not current_user.get("permissions", {}).get("datasources", {}).get("view"):
        raise PermissionError("Usuario sem permissao nesse recurso")


def build_datasource_payload(payload: Dict[str, Any], current_user: dict, existing: Dict[str, Any] | None = None) -> Tuple[str, Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    require_datasource_manager(current_user)

    kind = _normalize_kind(payload.get("kind"))
    if kind not in SUPPORTED_DATASOURCE_KINDS:
        raise ValueError("Tipo de datasource nao suportado.")

    tenant_id = _clean(payload.get("tenant_id")) or current_user["tenant_id"]
    if current_user["role"] != "master":
        tenant_id = current_user["tenant_id"]

    existing_config = (existing or {}).get("config_json") or {}
    existing_secret = (existing or {}).get("secret_json") or {}

    config: Dict[str, Any] = {}
    secret: Dict[str, Any] = {}

    if kind in {"postgresql", "mysql", "mariadb", "sqlserver"}:
        host = _clean(payload.get("host"))
        database_name = _clean(payload.get("database_name"))
        username = _clean(payload.get("username"))
        password = _clean(payload.get("password")) or existing_secret.get("password", "")
        port_default = {
            "postgresql": 5432,
            "mysql": 3306,
            "mariadb": 3306,
            "sqlserver": 1433,
        }[kind]
        port = _to_int(payload.get("port"), port_default)

        if not host or not database_name or not username or not password:
            raise ValueError("Host, porta, database, usuario e senha sao obrigatorios para esse tipo de conexao.")

        config = {
            "host": host,
            "port": port,
            "database_name": database_name,
            "username": username,
            "schema_name": _clean(payload.get("schema_name")),
            "ssl_mode": _clean(payload.get("ssl_mode")),
        }
        secret = {"password": password}

    elif kind == "sqlite":
        sqlite_mode = _clean(payload.get("sqlite_mode")) or _clean(existing_config.get("sqlite_mode")) or "url"
        sqlite_path = _clean(payload.get("sqlite_path")) or _clean(existing_config.get("sqlite_path"))
        sqlite_url = _clean(payload.get("sqlite_url")) or _clean(existing_config.get("sqlite_url"))
        if sqlite_mode == "url" and not sqlite_url:
            raise ValueError("Informe uma URL publica para o arquivo SQLite.")
        if sqlite_mode == "path" and not sqlite_path:
            raise ValueError("Informe um caminho interno para o arquivo SQLite.")
        config = {
            "sqlite_mode": sqlite_mode,
            "sqlite_path": sqlite_path,
            "sqlite_url": sqlite_url,
        }

    elif kind == "athena":
        access_key = _clean(payload.get("aws_access_key_id")) or existing_secret.get("aws_access_key_id", "")
        secret_key = _clean(payload.get("aws_secret_access_key")) or existing_secret.get("aws_secret_access_key", "")
        if not access_key or not secret_key:
            raise ValueError("AWS access key e secret key sao obrigatorias para Athena.")
        output_location = _clean(payload.get("output_location"))
        if not output_location.startswith("s3://"):
            raise ValueError("O output location do Athena precisa começar com s3://")

        config = {
            "region_name": _clean(payload.get("region_name")) or "us-east-1",
            "database_name": _clean(payload.get("database_name")),
            "catalog_name": _clean(payload.get("catalog_name")) or "AwsDataCatalog",
            "workgroup": _clean(payload.get("workgroup")),
            "output_location": output_location,
        }
        if not config["database_name"]:
            raise ValueError("Informe o database do Athena.")
        secret = {
            "aws_access_key_id": access_key,
            "aws_secret_access_key": secret_key,
            "aws_session_token": _clean(payload.get("aws_session_token")) or existing_secret.get("aws_session_token", ""),
        }

    elif kind == "bigquery":
        service_account_json = _clean(payload.get("service_account_json")) or existing_secret.get("service_account_json", "")
        if not service_account_json:
            raise ValueError("O JSON da service account e obrigatorio para BigQuery.")
        service_account_info = _parse_service_account_json(service_account_json)
        project_id = _clean(payload.get("project_id")) or _clean(service_account_info.get("project_id"))
        if not project_id:
            raise ValueError("Informe o project_id do BigQuery.")

        config = {
            "project_id": project_id,
            "dataset_name": _clean(payload.get("dataset_name")),
            "location": _clean(payload.get("location")),
            "gcs_temp_bucket": _clean(payload.get("gcs_temp_bucket")),
        }
        secret = {"service_account_json": service_account_json}

    meta = {
        "name": _clean(payload.get("name")),
        "kind": kind,
        "description": _clean(payload.get("description")),
        "is_active": bool(payload.get("is_active", True)),
        "tenant_id": tenant_id,
    }
    if not meta["name"]:
        raise ValueError("Informe um nome para a conexao.")

    return tenant_id, config, secret, meta


def summarize_datasource(kind: str, config_json: Dict[str, Any]) -> str:
    kind = _normalize_kind(kind)
    if kind in {"postgresql", "mysql", "mariadb", "sqlserver"}:
        return f"{config_json.get('host')}:{config_json.get('port')} / {config_json.get('database_name')}"
    if kind == "sqlite":
        return config_json.get("sqlite_url") or config_json.get("sqlite_path") or "-"
    if kind == "athena":
        return f"{config_json.get('region_name')} / {config_json.get('database_name')} / {config_json.get('output_location')}"
    if kind == "bigquery":
        bucket = config_json.get("gcs_temp_bucket")
        if bucket:
            return f"{config_json.get('project_id')} / {config_json.get('dataset_name') or '-'} / {bucket}"
        return f"{config_json.get('project_id')} / {config_json.get('dataset_name') or '-'}"
    return "-"


def serialize_datasource(row: Dict[str, Any], include_edit_payload: bool = False) -> Dict[str, Any]:
    config_json = row.get("config_json") or {}
    secret_json = row.get("secret_json") or {}

    item = {
        "id": row["id"],
        "tenant_id": row["tenant_id"],
        "tenant_name": row.get("tenant_name"),
        "name": row["name"],
        "kind": row["kind"],
        "description": row.get("description") or "",
        "summary": summarize_datasource(row["kind"], config_json),
        "is_active": row.get("is_active", True),
        "last_test_status": row.get("last_test_status"),
        "last_test_message": row.get("last_test_message"),
        "last_test_at": row["last_test_at"].isoformat() if row.get("last_test_at") else None,
        "created_at": row["created_at"].isoformat() if row.get("created_at") else None,
        "updated_at": row["updated_at"].isoformat() if row.get("updated_at") else None,
        "credentials": {
            "username": config_json.get("username", ""),
            "password": secret_json.get("password", ""),
            "aws_access_key_id": secret_json.get("aws_access_key_id", ""),
            "aws_secret_access_key": secret_json.get("aws_secret_access_key", ""),
            "aws_session_token": secret_json.get("aws_session_token", ""),
            "service_account_json": secret_json.get("service_account_json", ""),
        },
    }

    if include_edit_payload:
        item["form"] = {
            "name": row["name"],
            "kind": row["kind"],
            "description": row.get("description") or "",
            "tenant_id": row["tenant_id"],
            "is_active": row.get("is_active", True),
            "host": config_json.get("host", ""),
            "port": config_json.get("port", ""),
            "database_name": config_json.get("database_name", ""),
            "schema_name": config_json.get("schema_name", ""),
            "username": config_json.get("username", ""),
            "password": secret_json.get("password", ""),
            "ssl_mode": config_json.get("ssl_mode", ""),
            "catalog_name": config_json.get("catalog_name", ""),
            "region_name": config_json.get("region_name", ""),
            "workgroup": config_json.get("workgroup", ""),
            "output_location": config_json.get("output_location", ""),
            "aws_access_key_id": secret_json.get("aws_access_key_id", ""),
            "aws_secret_access_key": secret_json.get("aws_secret_access_key", ""),
            "aws_session_token": secret_json.get("aws_session_token", ""),
            "project_id": config_json.get("project_id", ""),
            "dataset_name": config_json.get("dataset_name", ""),
            "location": config_json.get("location", ""),
            "gcs_temp_bucket": config_json.get("gcs_temp_bucket", ""),
            "service_account_json": secret_json.get("service_account_json", ""),
            "sqlite_mode": config_json.get("sqlite_mode", "url"),
            "sqlite_path": config_json.get("sqlite_path", ""),
            "sqlite_url": config_json.get("sqlite_url", ""),
            "has_password": bool(secret_json.get("password")),
            "has_aws_secret_access_key": bool(secret_json.get("aws_secret_access_key")),
            "has_aws_session_token": bool(secret_json.get("aws_session_token")),
            "has_service_account_json": bool(secret_json.get("service_account_json")),
            "aws_access_key_preview": _mask_secret(secret_json.get("aws_access_key_id", "")),
        }

    return item


def test_datasource_connection(kind: str, config_json: Dict[str, Any], secret_json: Dict[str, Any]) -> Dict[str, Any]:
    kind = _normalize_kind(kind)
    if kind == "postgresql":
        return _test_postgresql(config_json, secret_json)
    if kind in {"mysql", "mariadb"}:
        return _test_mysql(config_json, secret_json, engine_name=kind)
    if kind == "sqlserver":
        return _test_sqlserver(config_json, secret_json)
    if kind == "sqlite":
        return _test_sqlite(config_json)
    if kind == "athena":
        return _test_athena(config_json, secret_json)
    if kind == "bigquery":
        return _test_bigquery(config_json, secret_json)
    raise ValueError("Tipo de datasource nao suportado.")


def _test_postgresql(config_json: Dict[str, Any], secret_json: Dict[str, Any]) -> Dict[str, Any]:
    conn = psycopg2.connect(
        host=config_json["host"],
        port=config_json["port"],
        dbname=config_json["database_name"],
        user=config_json["username"],
        password=secret_json["password"],
        connect_timeout=6,
    )
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT version()")
            version = cur.fetchone()[0]
        return {"message": f"Conexao PostgreSQL validada. {version}"}
    finally:
        conn.close()


def _test_mysql(config_json: Dict[str, Any], secret_json: Dict[str, Any], engine_name: str) -> Dict[str, Any]:
    conn = pymysql.connect(
        host=config_json["host"],
        port=int(config_json["port"]),
        user=config_json["username"],
        password=secret_json["password"],
        database=config_json["database_name"],
        connect_timeout=6,
        read_timeout=6,
        write_timeout=6,
    )
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT VERSION()")
            version = cur.fetchone()[0]
        return {"message": f"Conexao {engine_name} validada. {version}"}
    finally:
        conn.close()


def _test_sqlserver(config_json: Dict[str, Any], secret_json: Dict[str, Any]) -> Dict[str, Any]:
    conn = pytds.connect(
        dsn=config_json["host"],
        port=int(config_json["port"]),
        database=config_json["database_name"],
        user=config_json["username"],
        password=secret_json["password"],
        login_timeout=6,
        timeout=6,
        as_dict=True,
    )
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT @@VERSION AS version")
            row = cur.fetchone()
        return {"message": f"Conexao SQL Server validada. {row['version']}"}
    finally:
        conn.close()


def _test_sqlite(config_json: Dict[str, Any]) -> Dict[str, Any]:
    sqlite_mode = config_json.get("sqlite_mode", "url")
    file_path = config_json.get("sqlite_path", "")
    temp_path = None

    if sqlite_mode == "url":
        sqlite_url = config_json.get("sqlite_url", "")
        if not sqlite_url:
            raise ValueError("Informe uma URL publica para o arquivo SQLite.")
        with httpx.Client(timeout=15.0, follow_redirects=True) as client:
            response = client.get(sqlite_url)
            response.raise_for_status()
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".sqlite")
        temp_file.write(response.content)
        temp_file.flush()
        temp_file.close()
        temp_path = temp_file.name
        file_path = temp_path

    conn = sqlite3.connect(file_path)
    try:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM sqlite_master")
        total = cur.fetchone()[0]
        return {"message": f"Arquivo SQLite validado. Objetos em sqlite_master: {total}"}
    finally:
        conn.close()
        if temp_path and os.path.exists(temp_path):
            os.unlink(temp_path)


def _test_athena(config_json: Dict[str, Any], secret_json: Dict[str, Any]) -> Dict[str, Any]:
    client = boto3.client(
        "athena",
        region_name=config_json["region_name"],
        aws_access_key_id=secret_json["aws_access_key_id"],
        aws_secret_access_key=secret_json["aws_secret_access_key"],
        aws_session_token=secret_json.get("aws_session_token") or None,
    )

    query_context = {"Database": config_json["database_name"]}
    if config_json.get("catalog_name"):
        query_context["Catalog"] = config_json["catalog_name"]

    request_args = {
        "QueryString": "SELECT 1 AS ok",
        "QueryExecutionContext": query_context,
        "ResultConfiguration": {"OutputLocation": config_json["output_location"]},
    }
    if config_json.get("workgroup"):
        request_args["WorkGroup"] = config_json["workgroup"]

    response = client.start_query_execution(**request_args)
    query_execution_id = response["QueryExecutionId"]

    for _ in range(20):
        execution = client.get_query_execution(QueryExecutionId=query_execution_id)
        status = execution["QueryExecution"]["Status"]["State"]
        if status == "SUCCEEDED":
            return {"message": f"Conexao Athena validada. QueryExecutionId: {query_execution_id}"}
        if status in {"FAILED", "CANCELLED"}:
            reason = execution["QueryExecution"]["Status"].get("StateChangeReason", status)
            raise ValueError(f"A consulta de teste do Athena falhou: {reason}")
        time.sleep(1)

    raise TimeoutError("A consulta de teste do Athena nao terminou a tempo.")


def _test_bigquery(config_json: Dict[str, Any], secret_json: Dict[str, Any]) -> Dict[str, Any]:
    service_account_info = _parse_service_account_json(secret_json["service_account_json"])
    credentials = service_account.Credentials.from_service_account_info(service_account_info)
    client = bigquery.Client(
        project=config_json["project_id"],
        credentials=credentials,
        location=config_json.get("location") or None,
    )

    job = client.query("SELECT 1 AS ok")
    rows = list(job.result(timeout=20))
    if not rows:
        raise ValueError("BigQuery nao retornou resultado na consulta de teste.")

    if config_json.get("dataset_name"):
        dataset_ref = f"{config_json['project_id']}.{config_json['dataset_name']}"
        client.get_dataset(dataset_ref)
        return {"message": f"Conexao BigQuery validada. Dataset encontrado: {dataset_ref}"}

    return {"message": f"Conexao BigQuery validada no projeto {config_json['project_id']}."}
