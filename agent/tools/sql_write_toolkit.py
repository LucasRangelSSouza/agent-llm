import sqlite3
from typing import Any, Callable, Optional

import psycopg2
from psycopg2.extras import RealDictCursor

from agent.tools.sql_query_toolkit import SQLQueryToolkit


class SQLWriteToolkit(SQLQueryToolkit):
    """
    Executa operacoes de escrita em datasource: insert, update e delete.
    """

    def execute_sql_write(self) -> Callable[..., str]:
        def _tool(
            sql: str,
            engine: Optional[str] = None,
            datasource_name: Optional[str] = None,
            datasource_id: Optional[str] = None,
            template_key: Optional[str] = None,
            tenant_key: Optional[str] = None,
        ) -> str:
            try:
                params = self._parse_input(
                    sql=sql,
                    engine=engine,
                    datasource_name=datasource_name,
                    datasource_id=datasource_id,
                    template_key=template_key or tenant_key,
                )
                query = (params.get("sql") or "").strip()
                if not query:
                    return self._json_error("Campo 'sql' e obrigatorio.")
                self._validate_write_sql(query)

                template = self._resolve_template(params.get("template_key"))
                datasource = self._select_datasource(
                    template=template,
                    engine=params.get("engine"),
                    datasource_name=params.get("datasource_name") or params.get("datasource") or params.get("database"),
                    datasource_id=params.get("datasource_id"),
                )
                if not datasource:
                    return self._json_error("Nenhum datasource compativel foi encontrado no template.")

                payload = self._execute_write(datasource, query)
                payload.update(
                    {
                        "success": True,
                        "engine": self._normalize_engine(datasource.get("kind")),
                        "datasource_id": datasource.get("id"),
                        "datasource_name": datasource.get("name"),
                    }
                )
                return self._json_success_write(payload)
            except Exception as exc:
                return self._json_error(str(exc))

        return _tool

    def _validate_write_sql(self, query: str) -> None:
        normalized = " ".join((query or "").strip().lower().split())
        if normalized.startswith("select"):
            raise ValueError("Esta tool aceita apenas INSERT, UPDATE ou DELETE.")
        if not any(token in normalized for token in ("insert ", "update ", "delete ")):
            raise ValueError("A SQL precisa conter uma operacao de escrita: INSERT, UPDATE ou DELETE.")

    def _execute_write(self, datasource: dict, query: str) -> dict:
        engine = self._normalize_engine(datasource.get("kind"))
        if engine == "postgresql":
            return self._execute_write_postgres(datasource, query)
        if engine in {"mysql", "mariadb"}:
            return self._execute_write_mysql(datasource, query)
        if engine == "sqlserver":
            return self._execute_write_sqlserver(datasource, query)
        if engine == "sqlite":
            return self._execute_write_sqlite(datasource, query)
        raise ValueError(f"Engine nao suportado para escrita: {datasource.get('kind')}")

    def _execute_write_postgres(self, datasource: dict, query: str) -> dict:
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
            with conn:
                with conn.cursor() as cur:
                    cur.execute(query)
                    return self._collect_write_result(cur)
        finally:
            conn.close()

    def _execute_write_mysql(self, datasource: dict, query: str) -> dict:
        import pymysql

        config, secret = self._config_secret(datasource)
        conn = pymysql.connect(
            host=config.get("host"),
            port=int(config.get("port") or 3306),
            user=config.get("username") or secret.get("username"),
            password=secret.get("password") or config.get("password"),
            database=config.get("database_name") or config.get("database"),
            cursorclass=pymysql.cursors.DictCursor,
            autocommit=False,
        )
        try:
            with conn.cursor() as cur:
                cur.execute(query)
                payload = self._collect_write_result(cur)
            conn.commit()
            return payload
        finally:
            conn.close()

    def _execute_write_sqlserver(self, datasource: dict, query: str) -> dict:
        import pytds

        config, secret = self._config_secret(datasource)
        conn = pytds.connect(
            server=config.get("host"),
            port=int(config.get("port") or 1433),
            database=config.get("database_name") or config.get("database"),
            user=config.get("username") or secret.get("username"),
            password=secret.get("password") or config.get("password"),
            as_dict=True,
            autocommit=False,
        )
        try:
            with conn.cursor() as cur:
                cur.execute(query)
                payload = self._collect_write_result(cur)
            conn.commit()
            return payload
        finally:
            conn.close()

    def _execute_write_sqlite(self, datasource: dict, query: str) -> dict:
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
            payload = self._collect_write_result(cur)
            conn.commit()
            return payload
        finally:
            conn.close()

    def _collect_write_result(self, cur: Any) -> dict:
        affected_rows = getattr(cur, "rowcount", None)
        if getattr(cur, "description", None):
            columns = [item[0] for item in cur.description]
            rows = cur.fetchall()
            normalized_rows = [dict(row) if not isinstance(row, tuple) else dict(zip(columns, row)) for row in rows]
            return {
                "affected_rows": affected_rows,
                "columns": columns,
                "rows": normalized_rows,
                "returned_rows": len(normalized_rows),
            }
        return {
            "affected_rows": affected_rows,
            "columns": [],
            "rows": [],
            "returned_rows": 0,
        }

    def _json_success_write(self, payload: dict) -> str:
        import json

        return json.dumps(payload, ensure_ascii=False, default=self._json_default)
