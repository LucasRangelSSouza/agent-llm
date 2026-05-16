import json
import re
from io import BytesIO
from typing import Any, Callable, Optional

import pandas as pd
from openpyxl import load_workbook
from openpyxl.styles import Font

from agent.tools.sql_query_toolkit import SQLQueryToolkit
from agent.tools.artifact_store import load_dataset_artifact
from ui.backend.services.file_storage import save_file_bytes


class XLSXReportToolkit(SQLQueryToolkit):
    """
    Exporta um dataset artifact ou dados diretos para XLSX e publica o arquivo
    no storage.
    """

    def export_sql_to_xlsx(self) -> Callable[..., str]:
        def _tool(
            artifact_url: Optional[str] = None,
            artifact_id: Optional[str] = None,
            label: str = "Relatorio",
            data: Optional[Any] = None,
            file_name: Optional[str] = None,
        ) -> str:
            try:
                dataframe, manifest = self._resolve_dataframe(
                    artifact_url=artifact_url,
                    artifact_id=artifact_id,
                    data=data,
                )

                binary = self._build_xlsx_bytes(dataframe, label=label)
                final_filename = self._normalize_filename(file_name or label)
                stored = save_file_bytes(
                    tenant_id=self.tenant_id,
                    user_id=self.user_id,
                    chat_id=self.session_id,
                    filename=final_filename,
                    content=binary,
                    content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    kind="report_export",
                    metadata={
                        "module_name": self.module_name,
                        "agent_name": self.agent_name,
                        "label": label,
                        "artifact_id": manifest.get("artifact_id") if manifest else None,
                        "artifact_url": ((manifest.get("storage") or {}).get("manifest_url")) if manifest else artifact_url,
                    },
                    path_prefix=f"tenants/{self.tenant_id or 'unknown'}/reports/xlsx",
                )

                return json.dumps(
                    {
                        "success": True,
                        "label": label,
                        "file_name": final_filename,
                        "row_count": int(dataframe.shape[0]),
                        "columns": [str(column) for column in dataframe.columns],
                        "artifact_source": {
                            "artifact_id": manifest.get("artifact_id") if manifest else None,
                            "artifact_url": ((manifest.get("storage") or {}).get("manifest_url")) if manifest else artifact_url,
                        },
                        "public_url": stored.get("public_url"),
                        "bucket": stored.get("bucket"),
                        "object_key": stored.get("object_key"),
                        "file_id": stored.get("id"),
                    },
                    ensure_ascii=False,
                    default=self._json_default,
                )
            except Exception as exc:
                return self._json_error(str(exc))

        return _tool

    def _resolve_dataframe(self, *, artifact_url: Optional[str], artifact_id: Optional[str], data: Optional[Any]) -> tuple[pd.DataFrame, Optional[dict]]:
        if artifact_url or artifact_id:
            manifest, dataframe = load_dataset_artifact(artifact_url=artifact_url, artifact_id=artifact_id)
            return dataframe, manifest
        if isinstance(data, str):
            parsed = json.loads(data)
            if isinstance(parsed, list):
                return pd.DataFrame(parsed), None
            if isinstance(parsed, dict) and isinstance(parsed.get("rows"), list):
                return pd.DataFrame(parsed.get("rows") or []), None
        if isinstance(data, list):
            return pd.DataFrame(data), None
        if isinstance(data, dict) and isinstance(data.get("rows"), list):
            return pd.DataFrame(data.get("rows") or []), None
        raise ValueError("Informe artifact_url/artifact_id ou data em formato tabular.")

    def _build_xlsx_bytes(self, dataframe: pd.DataFrame, *, label: str) -> bytes:
        sheet_name = self._normalize_sheet_name(label)
        output = BytesIO()
        with pd.ExcelWriter(output, engine="openpyxl") as writer:
            dataframe.to_excel(writer, index=False, sheet_name=sheet_name)
        output.seek(0)

        workbook = load_workbook(output)
        worksheet = workbook[sheet_name]
        bold_font = Font(bold=True)
        for cell in worksheet[1]:
            cell.font = bold_font
        for column_cells in worksheet.columns:
            column_letter = column_cells[0].column_letter
            max_length = 0
            for cell in column_cells:
                text = "" if cell.value is None else str(cell.value)
                max_length = max(max_length, len(text))
            worksheet.column_dimensions[column_letter].width = min(max(max_length + 2, 12), 80)

        final_buffer = BytesIO()
        workbook.save(final_buffer)
        workbook.close()
        final_buffer.seek(0)
        return final_buffer.getvalue()

    def _normalize_sheet_name(self, value: str) -> str:
        name = re.sub(r'[:\\/*?\[\]]', "_", (value or "Relatorio").strip())
        return name[:31] or "Relatorio"

    def _normalize_filename(self, value: str) -> str:
        base = re.sub(r"[^A-Za-z0-9._-]+", "_", (value or "relatorio").strip()).strip("._") or "relatorio"
        if not base.lower().endswith(".xlsx"):
            base = f"{base}.xlsx"
        return base
