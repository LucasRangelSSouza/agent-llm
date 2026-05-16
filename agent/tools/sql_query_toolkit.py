import datetime as dt
import decimal
import json
import sqlite3
import time
from typing import Any, Dict, Iterable, List, Optional, Tuple

import boto3
import pandas as pd
import psycopg2
from psycopg2.extras import RealDictCursor

from agent.infrastructure.runtime.template_store import load_runtime_templates
from agent.tools.artifact_store import artifact_summary_text, save_dataset_artifact


ENGINE_ALIASES = {
    "postgres": "postgresql",
    "postgre": "postgresql",
    "postgree": "postgresql",
    "postgresql": "postgresql",
    "pgsql": "postgresql",
    "mysql": "mysql",
    "mariadb": "mariadb",
    "sqlserver": "sqlserver",
    "sql_server": "sqlserver",
    "mssql": "sqlserver",
    "sqlite": "sqlite",
    "athena": "athena",
    "bigquery": "bigquery",
    "bq": "bigquery",
}


class SQLQueryToolkit:
    """
    Toolkit universal de SQL.

    O agente informa a query e, opcionalmente, o datasource/engine. O toolkit
    resolve as credenciais no template ativo e devolve sempre uma string JSON.
    """

    def __init__(
        self,
        template: Optional[dict] = None,
        module_name: Optional[str] = None,
        agent_name: Optional[str] = None,
        tenant_id: Optional[str] = None,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        linked_files: Optional[List[dict]] = None,
        linked_secrets: Optional[List[dict]] = None,
        **_: Any,
    ) -> None:
        self.template = template or {}
        self.module_name = module_name
        self.agent_name = agent_name
        self.tenant_id = tenant_id
        self.session_id = session_id
        self.user_id = user_id
        self.linked_files = list(linked_files or [])
        self.linked_secrets = list(linked_secrets or [])

    def run_sql_query(self):
        def _tool(
            sql: str,
            engine: Optional[str] = None,
            datasource_name: Optional[str] = None,
            datasource_id: Optional[str] = None,
            template_key: Optional[str] = None,
            tenant_key: Optional[str] = None,
            max_rows: int = 100,
        ) -> str:
            try:
                params = self._parse_input(
                    sql=sql,
                    engine=engine,
                    datasource_name=datasource_name,
                    datasource_id=datasource_id,
                    template_key=template_key or tenant_key,
                    max_rows=max_rows,
                )
                query = (params.get("sql") or params.get("query") or "").strip()
                if not query:
                    return self._json_error("Campo 'sql' e obrigatorio.")

                template = self._resolve_template(params.get("template_key"))
                datasource = self._select_datasource(
                    template=template,
                    engine=params.get("engine"),
                    datasource_name=params.get("datasource_name") or params.get("datasource") or params.get("database"),
                    datasource_id=params.get("datasource_id"),
                )
                if not datasource:
                    return self._json_error("Nenhum datasource compativel foi encontrado no template.")

                rows, columns, truncated = self._execute(datasource, query, int(params.get("max_rows") or 100))
                artifact = save_dataset_artifact(
                    tenant_id=self.tenant_id,
                    user_id=self.user_id,
                    chat_id=self.session_id,
                    module_name=self.module_name,
                    agent_name=self.agent_name,
                    label=f"{self.agent_name or 'sql'}_dataset",
                    dataframe=pd.DataFrame(rows, columns=columns or None),
                    source_tool="sql_query_toolkit.run_sql_query",
                    source_type="sql",
                    metadata={
                        "sql": query,
                        "datasource_id": datasource.get("id"),
                        "datasource_name": datasource.get("name"),
                        "engine": self._normalize_engine(datasource.get("kind")),
                        "truncated": truncated,
                    },
                )
                return self._json_success(datasource, rows, columns, truncated, artifact)
            except Exception as exc:
                return self._json_error(str(exc))

        return _tool

    def describe_datasources(self):
        def _tool(template_key: Optional[str] = None, tenant_key: Optional[str] = None) -> str:
            try:
                template = self._resolve_template(template_key or tenant_key)
                items = []
                for datasource in self._iter_datasources(template):
                    config = datasource.get("config") or {}
                    safe_config = {
                        key: value
                        for key, value in config.items()
                        if "password" not in key.lower()
                        and "secret" not in key.lower()
                        and "key" not in key.lower()
                        and "token" not in key.lower()
                    }
                    items.append(
                        {
                            "id": datasource.get("id"),
                            "name": datasource.get("name"),
                            "kind": datasource.get("kind"),
                            "description": datasource.get("description") or "",
                            "config": safe_config,
                        }
                    )
                return json.dumps({"success": True, "datasources": items}, ensure_ascii=False, default=self._json_default)
            except Exception as exc:
                return self._json_error(str(exc))

        return _tool

    def _parse_input(self, **kwargs: Any) -> Dict[str, Any]:
        raw_sql = kwargs.pop("sql")
        if isinstance(raw_sql, dict):
            payload = dict(raw_sql)
        elif isinstance(raw_sql, str):
            text = raw_sql.strip()
            if text.startswith("{") and text.endswith("}"):
                try:
                    payload = json.loads(text)
                except Exception:
                    payload = {"sql": raw_sql}
            else:
                payload = {"sql": raw_sql}
        else:
            payload = {"sql": str(raw_sql)}

        for key, value in kwargs.items():
            if value not in (None, ""):
                payload[key] = value
        return payload

    def _resolve_template(self, template_key: Optional[str]) -> dict:
        if template_key:
            loaded = load_runtime_templates(str(template_key))
            if loaded:
                return loaded
        return self.template or {}

    def _iter_datasources(self, template: dict) -> Iterable[dict]:
        module_names = [self.module_name] if self.module_name else []
        module_names.extend(name for name in template.keys() if name not in module_names)
        for module_name in module_names:
            module_payload = template.get(module_name) or {}
            for datasource in module_payload.get("datasources_catalog") or []:
                if isinstance(datasource, dict):
                    yield datasource

    def _select_datasource(
        self,
        template: dict,
        engine: Optional[str],
        datasource_name: Optional[str],
        datasource_id: Optional[str],
    ) -> Optional[dict]:
        datasources = list(self._iter_datasources(template))
        wanted_engine = self._normalize_engine(engine)
        wanted_name = self._normalize_text(datasource_name)
        wanted_id = self._normalize_text(datasource_id)

        candidates = []
        for datasource in datasources:
            kind = self._normalize_engine(datasource.get("kind"))
            score = 0
            if wanted_id and self._normalize_text(datasource.get("id")) == wanted_id:
                score += 100
            if wanted_name and self._normalize_text(datasource.get("name")) == wanted_name:
                score += 80
            if wanted_engine and kind == wanted_engine:
                score += 40
            if not wanted_engine and kind in set(ENGINE_ALIASES.values()):
                score += 10
            if score:
                candidates.append((score, datasource))

        if candidates:
            candidates.sort(key=lambda item: item[0], reverse=True)
            return candidates[0][1]
        if len(datasources) == 1:
            return datasources[0]
        return None

    def _execute(self, datasource: dict, query: str, max_rows: int) -> Tuple[List[dict], List[str], bool]:
        engine = self._normalize_engine(datasource.get("kind"))
        if engine == "postgresql":
            return self._execute_postgres(datasource, query, max_rows)
        if engine in {"mysql", "mariadb"}:
            return self._execute_mysql(datasource, query, max_rows)
        if engine == "sqlserver":
            return self._execute_sqlserver(datasource, query, max_rows)
        if engine == "sqlite":
            return self._execute_sqlite(datasource, query, max_rows)
        if engine == "athena":
            return self._execute_athena(datasource, query, max_rows)
        if engine == "bigquery":
            return self._execute_bigquery(datasource, query, max_rows)
        raise ValueError(f"Engine nao suportado: {datasource.get('kind')}")

    def _execute_postgres(self, datasource: dict, query: str, max_rows: int):
        config, secret = self._config_secret(datasource)
        conn_kwargs = {
            "host": config.get("host"),
            "port": int(config.get("port") or 5432),
            "dbname": config.get("database_name") or config.get("database"),
            "user": config.get("username") or secret.get("username"),
            "password": secret.get("password") or config.get("password"),
            "cursor_factory": RealDictCursor,
        }
        if config.get("ssl_mode"):
            conn_kwargs["sslmode"] = config.get("ssl_mode")
        conn = psycopg2.connect(**conn_kwargs)
        try:
            with conn, conn.cursor() as cur:
                cur.execute(query)
                return self._fetch_cursor_rows(cur, max_rows)
        finally:
            conn.close()

    def _execute_mysql(self, datasource: dict, query: str, max_rows: int):
        import pymysql

        config, secret = self._config_secret(datasource)
        conn = pymysql.connect(
            host=config.get("host"),
            port=int(config.get("port") or 3306),
            user=config.get("username") or secret.get("username"),
            password=secret.get("password") or config.get("password"),
            database=config.get("database_name") or config.get("database"),
            cursorclass=pymysql.cursors.DictCursor,
        )
        try:
            with conn.cursor() as cur:
                cur.execute(query)
                return self._fetch_cursor_rows(cur, max_rows)
        finally:
            conn.close()

    def _execute_sqlserver(self, datasource: dict, query: str, max_rows: int):
        import pytds

        config, secret = self._config_secret(datasource)
        conn = pytds.connect(
            server=config.get("host"),
            port=int(config.get("port") or 1433),
            database=config.get("database_name") or config.get("database"),
            user=config.get("username") or secret.get("username"),
            password=secret.get("password") or config.get("password"),
            as_dict=True,
        )
        try:
            with conn.cursor() as cur:
                cur.execute(query)
                return self._fetch_cursor_rows(cur, max_rows)
        finally:
            conn.close()

    def _execute_sqlite(self, datasource: dict, query: str, max_rows: int):
        config, _ = self._config_secret(datasource)
        path = config.get("sqlite_path") or config.get("path")
        runtime_uri = datasource.get("runtime_uri") or ""
        if not path and runtime_uri.startswith("sqlite:///"):
            path = runtime_uri.replace("sqlite:///", "", 1)
            if not path.startswith("/") and path != ":memory:":
                path = "/" + path
        if not path:
            raise ValueError("Datasource SQLite sem caminho configurado.")
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        try:
            cur = conn.execute(query)
            return self._fetch_cursor_rows(cur, max_rows)
        finally:
            conn.close()

    def _execute_athena(self, datasource: dict, query: str, max_rows: int):
        config, secret = self._config_secret(datasource)
        client = boto3.client(
            "athena",
            region_name=config.get("region_name") or "us-east-1",
            aws_access_key_id=secret.get("aws_access_key_id") or config.get("aws_access_key_id"),
            aws_secret_access_key=secret.get("aws_secret_access_key") or config.get("aws_secret_access_key"),
            aws_session_token=secret.get("aws_session_token") or config.get("aws_session_token") or None,
        )
        context = {"Database": config.get("database_name") or config.get("database")}
        if config.get("catalog_name"):
            context["Catalog"] = config.get("catalog_name")
        request = {
            "QueryString": query,
            "QueryExecutionContext": context,
            "ResultConfiguration": {"OutputLocation": config.get("output_location")},
        }
        if config.get("workgroup"):
            request["WorkGroup"] = config.get("workgroup")
        execution_id = client.start_query_execution(**request)["QueryExecutionId"]
        self._wait_athena(client, execution_id)
        fetch_size = max(1, min(int(max_rows or 1) + 1, 1000))
        all_rows = []
        columns = []
        next_token = None
        header_consumed = False
        truncated = False

        while True:
            request = {
                "QueryExecutionId": execution_id,
                "MaxResults": fetch_size,
            }
            if next_token:
                request["NextToken"] = next_token
            result = client.get_query_results(**request)
            rows = result.get("ResultSet", {}).get("Rows", [])
            if rows and not header_consumed:
                columns = [col.get("VarCharValue", "") for col in rows[0].get("Data", [])]
                rows = rows[1:]
                header_consumed = True
            if columns:
                for row in rows:
                    all_rows.append(self._athena_row_to_dict(columns, row))
                    if len(all_rows) > max_rows:
                        truncated = True
                        return all_rows[:max_rows], columns, truncated
            next_token = result.get("NextToken")
            if not next_token:
                break
        return all_rows[:max_rows], columns, truncated

    def _execute_bigquery(self, datasource: dict, query: str, max_rows: int):
        from google.cloud import bigquery
        from google.oauth2 import service_account

        config, secret = self._config_secret(datasource)
        sa_raw = secret.get("service_account_json") or config.get("service_account_json")
        if isinstance(sa_raw, str):
            sa_info = json.loads(sa_raw)
        elif isinstance(sa_raw, dict):
            sa_info = sa_raw
        else:
            raise ValueError("BigQuery exige service_account_json no datasource.")
        credentials = service_account.Credentials.from_service_account_info(sa_info)
        project = config.get("project_id") or sa_info.get("project_id")
        client = bigquery.Client(project=project, credentials=credentials)
        job = client.query(query)
        rows_iter = job.result(max_results=max_rows + 1)
        rows = [dict(row.items()) for row in rows_iter]
        columns = [field.name for field in job.schema]
        return rows[:max_rows], columns, len(rows) > max_rows

    def _fetch_cursor_rows(self, cur: Any, max_rows: int):
        if not getattr(cur, "description", None):
            return [], [], False
        columns = [item[0] for item in cur.description]
        raw_rows = cur.fetchmany(max_rows + 1)
        rows = [dict(row) if not isinstance(row, tuple) else dict(zip(columns, row)) for row in raw_rows]
        return rows[:max_rows], columns, len(rows) > max_rows

    def _wait_athena(self, client: Any, execution_id: str) -> None:
        while True:
            response = client.get_query_execution(QueryExecutionId=execution_id)
            state = response["QueryExecution"]["Status"]["State"]
            if state == "SUCCEEDED":
                return
            if state in {"FAILED", "CANCELLED"}:
                reason = response["QueryExecution"]["Status"].get("StateChangeReason", state)
                raise ValueError(f"Athena query {state}: {reason}")
            time.sleep(1)

    def _athena_row_to_dict(self, columns: List[str], row: dict) -> dict:
        data = row.get("Data", [])
        return {
            column: (data[idx].get("VarCharValue") if idx < len(data) else None)
            for idx, column in enumerate(columns)
        }

    def _config_secret(self, datasource: dict) -> Tuple[dict, dict]:
        return datasource.get("config") or {}, datasource.get("secret") or {}

    def _normalize_engine(self, value: Optional[str]) -> Optional[str]:
        if not value:
            return None
        return ENGINE_ALIASES.get(str(value).strip().lower(), str(value).strip().lower())

    def _normalize_text(self, value: Optional[str]) -> str:
        return str(value or "").strip().lower()

    def _module_payload(self, template: Optional[dict] = None) -> dict:
        source = template or self.template or {}
        if self.module_name and isinstance(source.get(self.module_name), dict):
            return source.get(self.module_name) or {}
        for _, module_payload in source.items():
            if isinstance(module_payload, dict) and module_payload.get("submodules"):
                return module_payload
        return {}

    def _agent_payload(self, template: Optional[dict] = None) -> dict:
        module_payload = self._module_payload(template)
        submodules = module_payload.get("submodules") or {}
        if self.agent_name and isinstance(submodules.get(self.agent_name), dict):
            return submodules.get(self.agent_name) or {}
        return {}

    def _get_linked_files(self, template: Optional[dict] = None) -> List[dict]:
        agent_payload = self._agent_payload(template)
        files = agent_payload.get("linked_files")
        if isinstance(files, list) and files:
            return files
        return list(self.linked_files)

    def _get_linked_secrets(self, template: Optional[dict] = None) -> List[dict]:
        agent_payload = self._agent_payload(template)
        secrets = agent_payload.get("linked_secrets")
        if isinstance(secrets, list) and secrets:
            return secrets
        return list(self.linked_secrets)

    def _find_linked_file(self, file_name: str, template: Optional[dict] = None) -> Optional[dict]:
        target = self._normalize_text(file_name)
        if not target:
            return None
        files = self._get_linked_files(template)
        for item in files:
            candidates = [
                item.get("name"),
                item.get("original_filename"),
                item.get("url"),
                item.get("id"),
            ]
            if any(self._normalize_text(value) == target for value in candidates if value):
                return item
        for item in files:
            candidates = [item.get("name"), item.get("original_filename"), item.get("url"), item.get("id")]
            if any(target in self._normalize_text(value) for value in candidates if value):
                return item
        return None

    def _find_linked_secret(self, secret_name: str, template: Optional[dict] = None) -> Optional[dict]:
        target = self._normalize_text(secret_name)
        if not target:
            return None
        secrets = self._get_linked_secrets(template)
        for item in secrets:
            candidates = [item.get("name"), item.get("id")]
            if any(self._normalize_text(value) == target for value in candidates if value):
                return item
        for item in secrets:
            candidates = [item.get("name"), item.get("id")]
            if any(target in self._normalize_text(value) for value in candidates if value):
                return item
        return None

    def _json_success(self, datasource: dict, rows: List[dict], columns: List[str], truncated: bool, artifact: Optional[dict] = None) -> str:
        payload = {
            "success": True,
            "engine": self._normalize_engine(datasource.get("kind")),
            "datasource_id": datasource.get("id"),
            "datasource_name": datasource.get("name"),
            "row_count": len(rows),
            "columns": columns,
            "rows": rows,
            "truncated": truncated,
            "artifact": artifact,
            "artifact_summary": artifact_summary_text(artifact) if artifact else None,
        }
        return json.dumps(payload, ensure_ascii=False, default=self._json_default)

    def _json_error(self, message: str) -> str:
        return json.dumps({"success": False, "error": message}, ensure_ascii=False)

    def _json_default(self, value: Any) -> Any:
        if isinstance(value, (dt.date, dt.datetime)):
            return value.isoformat()
        if isinstance(value, decimal.Decimal):
            return float(value)
        return str(value)
