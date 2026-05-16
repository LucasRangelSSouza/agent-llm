# sql_export_excel_toolkit.py
# -*- coding: utf-8 -*-

"""
SqlExportExcelAthenaToolKit
===========================

- Entrada: SQL (Athena) + label
- Executa query no Athena
- Salva resultado em Excel (.xlsx)
- Nome do arquivo = label
- Nome da planilha = label
- Cabeçalhos em negrito
- Faz upload no S3
- Gera link HTTP autenticado (presigned URL)
- Retorno:
  - JSON com _meta
  - contendo apenas o link autenticado e resumo textual
"""

import os
import re
import time
import json
import logging
from typing import Any, List, Dict, Optional, Callable, Tuple, Union

import boto3
from botocore.exceptions import ClientError

try:
    import pandas as pd
except Exception as e:
    raise ImportError(
        "Dependências ausentes. Instale: pandas, openpyxl. "
        f"Erro original: {e}"
    )

try:
    from openpyxl import load_workbook
    from openpyxl.styles import Font
except Exception as e:
    raise ImportError(
        "Dependências ausentes. Instale: openpyxl. "
        f"Erro original: {e}"
    )

logger = logging.getLogger(__name__)


class SqlExportExcelAthenaToolKit:
    """
    Tool para exportar resultado de SQL Athena em Excel e devolver link autenticado.

    Variáveis de ambiente esperadas:
    - EXCEL_S3_BASE
    - ATHENA_OUTPUT_LOCATION
    - AWS_ACCESS_KEY_ID
    - AWS_SECRET_ACCESS_KEY
    - AWS_DEFAULT_REGION
    """

    def __init__(
        self,
        athena_database: Optional[str] = None,
        excel_s3_base: Optional[str] = None,
        athena_output_location: Optional[str] = None,
        region_name: Optional[str] = None,
        aws_access_key_id: Optional[str] = None,
        aws_secret_access_key: Optional[str] = None,
        aws_session_token: Optional[str] = None,
        poll_interval: int = 2,
        max_rows: int = 500000,
        presign_expires_seconds: int = 604800,
    ) -> None:
        self.region_name = region_name or "us-east-1"
        self.aws_access_key_id = aws_access_key_id or ""
        self.aws_secret_access_key = aws_secret_access_key or ""
        self.aws_session_token = aws_session_token or ""

        self.athena_database = athena_database or ""
        self.athena_output_location = athena_output_location or ""
        self.excel_s3_base = excel_s3_base or ""

        self.poll_interval = int(poll_interval)
        self.max_rows = int(max_rows)
        self.presign_expires_seconds = int(presign_expires_seconds)

        if not self.aws_access_key_id or not self.aws_secret_access_key:
            raise ValueError("Credenciais AWS ausentes (AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY).")
        if not self.excel_s3_base:
            raise ValueError("EXCEL_S3_BASE ausente.")
        if not self.excel_s3_base.startswith("s3://"):
            raise ValueError("EXCEL_S3_BASE deve ser s3://bucket/prefix/")

        self.athena_client = boto3.client(
            "athena",
            region_name=self.region_name,
            aws_access_key_id=self.aws_access_key_id,
            aws_secret_access_key=self.aws_secret_access_key,
            aws_session_token=self.aws_session_token or None,
        )
        self.s3_client = boto3.client(
            "s3",
            region_name=self.region_name,
            aws_access_key_id=self.aws_access_key_id,
            aws_secret_access_key=self.aws_secret_access_key,
            aws_session_token=self.aws_session_token or None,
        )

        self._ensure_athena_output_bucket_if_needed()

        logger.info(
            "[SqlExportExcelAthenaToolKit] Inicializado | Região=%s | AthenaOutput=%s | ExcelBase=%s",
            self.region_name, self.athena_output_location, self.excel_s3_base
        )

    # =========================================================================
    # Helpers
    # =========================================================================

    @staticmethod
    def _extract_bucket_name(s3_uri: str) -> str:
        if not s3_uri.startswith("s3://"):
            raise ValueError(f"S3 URI inválida: {s3_uri}")
        return s3_uri.replace("s3://", "", 1).split("/", 1)[0]

    @staticmethod
    def _split_s3_uri(s3_uri: str) -> Tuple[str, str]:
        s3_uri = s3_uri.strip()
        if not s3_uri.startswith("s3://"):
            raise ValueError(f"URI S3 inválida: {s3_uri}")
        no_scheme = s3_uri.replace("s3://", "", 1)
        parts = no_scheme.split("/", 1)
        bucket = parts[0]
        prefix = parts[1] if len(parts) > 1 else ""
        return bucket, prefix

    @staticmethod
    def _slugify(texto: str) -> str:
        texto = (texto or "").strip().lower()
        texto = re.sub(r"[^\w\s-]", "", texto, flags=re.UNICODE)
        texto = re.sub(r"[\s-]+", "_", texto, flags=re.UNICODE)
        texto = re.sub(r"_+", "_", texto).strip("_")
        return texto or "arquivo"

    @staticmethod
    def _sheet_name(label: str) -> str:
        """
        Excel limita sheet name a 31 caracteres e não permite alguns caracteres.
        """
        name = (label or "Planilha").strip()
        name = re.sub(r'[:\\/*?\[\]]', "_", name)
        name = name[:31].strip()
        return name or "Planilha"

    def _ensure_athena_output_bucket_if_needed(self) -> None:
        if not self.athena_output_location:
            return

        bucket_name = self._extract_bucket_name(self.athena_output_location)
        try:
            self.s3_client.head_bucket(Bucket=bucket_name)
        except ClientError as e:
            code = e.response["Error"].get("Code", "")
            if code in ("404", "NoSuchBucket", "NotFound"):
                create_kwargs: Dict[str, Any] = {"Bucket": bucket_name}
                if self.region_name != "us-east-1":
                    create_kwargs["CreateBucketConfiguration"] = {"LocationConstraint": self.region_name}
                self.s3_client.create_bucket(**create_kwargs)
            else:
                raise

    # =========================================================================
    # Athena
    # =========================================================================

    def _execute_athena_query(self, query: str) -> pd.DataFrame:
        """
        Executa query no Athena e retorna DataFrame.
        """
        if not isinstance(query, str) or not query.strip():
            raise ValueError("Nenhuma consulta SQL válida foi fornecida.")
        if not self.athena_database:
            raise ValueError("athena_database não configurado.")
        if not self.athena_output_location:
            raise ValueError("ATHENA_OUTPUT_LOCATION não configurado.")

        response = self.athena_client.start_query_execution(
            QueryString=query,
            QueryExecutionContext={"Database": self.athena_database},
            ResultConfiguration={"OutputLocation": self.athena_output_location},
        )
        qid = response["QueryExecutionId"]

        while True:
            status = self.athena_client.get_query_execution(QueryExecutionId=qid)
            state = status["QueryExecution"]["Status"]["State"]

            if state in ("SUCCEEDED", "FAILED", "CANCELLED"):
                if state != "SUCCEEDED":
                    reason = status["QueryExecution"]["Status"].get("StateChangeReason", "Sem motivo detalhado")
                    raise RuntimeError(f"Query falhou. Estado: {state}. Motivo: {reason}")
                break

            time.sleep(self.poll_interval)

        paginator = self.athena_client.get_paginator("get_query_results")
        pages = paginator.paginate(QueryExecutionId=qid)

        rows: List[Dict[str, Any]] = []
        column_info = None

        for page in pages:
            if column_info is None:
                column_info = page["ResultSet"]["ResultSetMetadata"]["ColumnInfo"]

            for row in page["ResultSet"]["Rows"]:
                # pula header
                if (
                    row.get("Data")
                    and "VarCharValue" in row["Data"][0]
                    and row["Data"][0]["VarCharValue"] == column_info[0]["Name"]
                ):
                    continue

                row_dict: Dict[str, Any] = {}
                for col, cell in zip(column_info, row.get("Data", [])):
                    row_dict[col["Name"]] = cell.get("VarCharValue", None)

                rows.append(row_dict)

                if self.max_rows and len(rows) >= self.max_rows:
                    raise RuntimeError(
                        f"Resultado excedeu max_rows={self.max_rows}. "
                        "Restrinja a SQL antes de exportar."
                    )

        return pd.DataFrame(rows)

    # =========================================================================
    # Excel
    # =========================================================================

    def _write_excel(
        self,
        df: pd.DataFrame,
        label: str,
    ) -> str:
        """
        Gera arquivo Excel local.
        - nome do arquivo = label
        - nome da planilha = label
        - header em negrito
        """
        ts = time.strftime("%Y%m%d_%H%M%S")
        safe_file_name = self._slugify(label)
        file_name = f"{safe_file_name}_{ts}.xlsx"
        local_path = os.path.join(os.getcwd(), file_name)

        sheet_name = self._sheet_name(label)

        with pd.ExcelWriter(local_path, engine="openpyxl") as writer:
            df.to_excel(writer, index=False, sheet_name=sheet_name)

        wb = load_workbook(local_path)
        ws = wb[sheet_name]

        # Header em negrito
        bold_font = Font(bold=True)
        for cell in ws[1]:
            cell.font = bold_font

        # Ajuste simples de largura de coluna
        for col_cells in ws.columns:
            max_length = 0
            col_letter = col_cells[0].column_letter
            for cell in col_cells:
                try:
                    val = "" if cell.value is None else str(cell.value)
                    if len(val) > max_length:
                        max_length = len(val)
                except Exception:
                    pass
            ws.column_dimensions[col_letter].width = min(max(max_length + 2, 12), 60)

        wb.save(local_path)
        wb.close()

        return local_path

    def _upload_file_s3_and_presign(self, local_path: str, label: str) -> Tuple[str, str]:
        bucket, base_prefix = self._split_s3_uri(self.excel_s3_base)
        file_name = os.path.basename(local_path)
        key = base_prefix.rstrip("/") + "/" + file_name if base_prefix else file_name

        self.s3_client.upload_file(local_path, bucket, key)

        try:
            os.remove(local_path)
        except Exception:
            pass

        file_s3_url = f"s3://{bucket}/{key}"

        file_http_url = self.s3_client.generate_presigned_url(
            ClientMethod="get_object",
            Params={"Bucket": bucket, "Key": key},
            ExpiresIn=self.presign_expires_seconds,
        )

        return file_s3_url, file_http_url

    # =========================================================================
    # Texto
    # =========================================================================

    @staticmethod
    def _build_summary_txt(label: str, row_count: int, col_count: int) -> str:
        return (
            f"Arquivo '{label}' gerado com sucesso em Excel, contendo "
            f"{row_count} linhas e {col_count} colunas."
        )

    # =========================================================================
    # Tool interna por payload
    # =========================================================================

    def _run_export_excel_payload(self) -> Callable[[Union[str, Dict[str, Any]]], str]:
        """
        Retorna uma função tool:
        - Entrada: dict ou JSON string
        - Saída: JSON string
        """
        def _tool(input_payload: Union[str, Dict[str, Any]]) -> str:
            # 0) parse
            if input_payload is None:
                return json.dumps(
                    [{"_meta": {"ok": False, "error": "Nenhuma entrada foi fornecida (esperado JSON)."}}],
                    ensure_ascii=False,
                    indent=2,
                )

            if isinstance(input_payload, str):
                if not input_payload.strip():
                    return json.dumps(
                        [{"_meta": {"ok": False, "error": "Entrada vazia (esperado JSON)."}}],
                        ensure_ascii=False,
                        indent=2,
                    )
                try:
                    payload = json.loads(input_payload)
                except Exception as e:
                    return json.dumps(
                        [{"_meta": {"ok": False, "error": f"Entrada não é JSON válido: {e}"}}],
                        ensure_ascii=False,
                        indent=2,
                    )
            elif isinstance(input_payload, dict):
                payload = input_payload
            else:
                return json.dumps(
                    [{"_meta": {"ok": False, "error": "Entrada deve ser JSON string ou dict."}}],
                    ensure_ascii=False,
                    indent=2,
                )

            sql = str(payload.get("sql") or "").strip()
            label = str(payload.get("label") or "export_athena").strip()

            if not sql:
                return json.dumps(
                    [{"_meta": {"ok": False, "error": "SQL vazia ou inválida."}}],
                    ensure_ascii=False,
                    indent=2,
                )

            # 1) query
            try:
                df = self._execute_athena_query(sql)
            except Exception as e:
                return json.dumps(
                    [{"_meta": {"ok": False, "stage": "athena_query", "error": str(e)}}],
                    ensure_ascii=False,
                    indent=2,
                )

            # 2) excel
            try:
                local_path = self._write_excel(df=df, label=label)
            except Exception as e:
                return json.dumps(
                    [{"_meta": {"ok": False, "stage": "write_excel", "error": str(e)}}],
                    ensure_ascii=False,
                    indent=2,
                )

            # 3) s3 + presigned
            try:
                file_s3_url, file_http_url = self._upload_file_s3_and_presign(local_path=local_path, label=label)
            except Exception as e:
                return json.dumps(
                    [{"_meta": {"ok": False, "stage": "upload_s3", "error": str(e)}}],
                    ensure_ascii=False,
                    indent=2,
                )

            # 4) summary
            row_count = int(df.shape[0])
            col_count = int(df.shape[1])
            summary_txt = self._build_summary_txt(label=label, row_count=row_count, col_count=col_count)

            meta = {
                "ok": True,
                "label": label,
                "row_count": row_count,
                "col_count": col_count,
                "file_s3_url": file_s3_url,
                "file_http_url": file_http_url,
                "summary_txt": summary_txt,
            }

            # retorno enxuto
            return json.dumps(
                [{"_meta": meta}],
                ensure_ascii=False,
                indent=2,
            )

        return _tool

    # =========================================================================
    # Tool pública com assinatura explícita
    # =========================================================================

    def run_export_excel_tool(self) -> Callable[..., str]:
        """
        Tool com assinatura explícita:
        run_export_excel(sql="...", label="Meu Arquivo")

        Internamente, monta o payload e chama a tool original.
        """
        base_tool = self._run_export_excel_payload()

        def _tool(
            sql: str,
            label: str = "export_athena",
        ) -> str:
            if not isinstance(sql, str) or not sql.strip():
                return json.dumps(
                    [{"_meta": {"ok": False, "error": "SQL vazia ou inválida."}}],
                    ensure_ascii=False,
                    indent=2,
                )

            payload = {
                "sql": sql.strip(),
                "label": (label or "export_athena").strip(),
            }

            return base_tool(payload)

        return _tool
