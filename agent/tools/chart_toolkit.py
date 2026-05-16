import json
import re
from typing import Any, Callable, Dict, Optional

import pandas as pd
import plotly.graph_objects as go
import plotly.io as pio

from agent.tools.sql_query_toolkit import SQLQueryToolkit
from agent.tools.artifact_store import load_dataset_artifact
from ui.backend.services.file_storage import save_file_bytes


class ChartToolkit(SQLQueryToolkit):
    """
    Gera grafico interativo em Plotly a partir de um dataset artifact ou de
    dados diretos e publica uma imagem PNG/JPG do grafico no storage.
    """

    SUPPORTED_CHART_TYPES = {"bar", "line", "area", "scatter", "pie", "indicator"}

    def generate_chart(self) -> Callable[..., str]:
        def _tool(
            artifact_url: Optional[str] = None,
            artifact_id: Optional[str] = None,
            chart_type: str = "bar",
            label: str = "Grafico",
            data: Optional[Any] = None,
            x_col: Optional[str] = None,
            y_col: Optional[str] = None,
            series_col: Optional[str] = None,
            names_col: Optional[str] = None,
            values_col: Optional[str] = None,
            image_format: str = "png",
        ) -> str:
            try:
                dataframe, manifest = self._resolve_dataframe(
                    artifact_url=artifact_url,
                    artifact_id=artifact_id,
                    data=data,
                )
                if dataframe.empty:
                    return self._json_error("Nao ha linhas para gerar o grafico.")

                figure = self._build_figure(
                    dataframe=dataframe,
                    chart_type=chart_type,
                    label=label,
                    x_col=x_col,
                    y_col=y_col,
                    series_col=series_col,
                    names_col=names_col,
                    values_col=values_col,
                )
                plotly_json = json.loads(pio.to_json(figure, pretty=False))
                image_payload = self._export_chart_image(
                    figure=figure,
                    label=label,
                    image_format=image_format,
                )

                return json.dumps(
                    {
                        "success": True,
                        "label": label,
                        "chart_type": chart_type,
                        "row_count": int(dataframe.shape[0]),
                        "columns": [str(column) for column in dataframe.columns],
                        "artifact_source": {
                            "artifact_id": manifest.get("artifact_id") if manifest else None,
                            "artifact_url": ((manifest.get("storage") or {}).get("manifest_url")) if manifest else artifact_url,
                            "artifact_kind": manifest.get("artifact_kind") if manifest else None,
                        },
                        "plotly_json": plotly_json,
                        "image_public_url": image_payload.get("public_url"),
                        "image_file_id": image_payload.get("id"),
                        "image_format": image_payload.get("format"),
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

    def _build_figure(
        self,
        *,
        dataframe: pd.DataFrame,
        chart_type: str,
        label: str,
        x_col: Optional[str],
        y_col: Optional[str],
        series_col: Optional[str],
        names_col: Optional[str],
        values_col: Optional[str],
    ) -> go.Figure:
        normalized_chart_type = str(chart_type or "bar").strip().lower()
        if normalized_chart_type not in self.SUPPORTED_CHART_TYPES:
            raise ValueError(f"chart_type invalido: {normalized_chart_type}. Use: {sorted(self.SUPPORTED_CHART_TYPES)}")

        figure = go.Figure()
        if normalized_chart_type == "pie":
            name_field = names_col or x_col or dataframe.columns[0]
            value_field = values_col or y_col or dataframe.columns[1]
            self._ensure_columns(dataframe, [name_field, value_field])
            figure.add_trace(
                go.Pie(
                    labels=dataframe[name_field].astype(str),
                    values=pd.to_numeric(dataframe[value_field], errors="coerce"),
                    textinfo="percent+label",
                )
            )
        elif normalized_chart_type == "indicator":
            value_field = values_col or y_col or dataframe.columns[0]
            self._ensure_columns(dataframe, [value_field])
            numeric_series = pd.to_numeric(dataframe[value_field], errors="coerce").dropna()
            if numeric_series.empty:
                raise ValueError("Nao ha valor numerico valido para o grafico indicator.")
            figure.add_trace(
                go.Indicator(
                    mode="number",
                    value=float(numeric_series.iloc[0]),
                    title={"text": label},
                )
            )
        elif normalized_chart_type in {"bar", "line", "area", "scatter"}:
            x_field = x_col or dataframe.columns[0]
            y_field = y_col or dataframe.columns[1]
            self._ensure_columns(dataframe, [x_field, y_field])
            work = dataframe.copy()
            work[y_field] = pd.to_numeric(work[y_field], errors="coerce")
            work = work.dropna(subset=[y_field])
            if work.empty:
                raise ValueError("Nao ha valores numericos validos para o eixo Y.")

            if series_col and series_col in work.columns:
                for series_name, subset in work.groupby(series_col):
                    self._append_xy_trace(
                        figure=figure,
                        chart_type=normalized_chart_type,
                        x_values=subset[x_field],
                        y_values=subset[y_field],
                        name=str(series_name),
                    )
            else:
                self._append_xy_trace(
                    figure=figure,
                    chart_type=normalized_chart_type,
                    x_values=work[x_field],
                    y_values=work[y_field],
                    name=label,
                )
        else:
            raise ValueError(f"chart_type nao suportado: {normalized_chart_type}")

        figure.update_layout(
            title=label,
            template="plotly_white",
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            margin={"l": 32, "r": 24, "t": 64, "b": 40},
            legend={"orientation": "h", "yanchor": "bottom", "y": 1.02, "x": 0},
        )
        return figure

    def _append_xy_trace(self, *, figure: go.Figure, chart_type: str, x_values: Any, y_values: Any, name: str) -> None:
        if chart_type == "bar":
            figure.add_trace(go.Bar(x=list(x_values), y=list(y_values), name=name))
            return
        if chart_type == "line":
            figure.add_trace(go.Scatter(x=list(x_values), y=list(y_values), mode="lines+markers", name=name))
            return
        if chart_type == "area":
            figure.add_trace(go.Scatter(x=list(x_values), y=list(y_values), mode="lines", stackgroup="one", name=name))
            return
        if chart_type == "scatter":
            figure.add_trace(go.Scatter(x=list(x_values), y=list(y_values), mode="markers", name=name))
            return
        raise ValueError(f"chart_type nao suportado para serie XY: {chart_type}")

    def _export_chart_image(self, *, figure: go.Figure, label: str, image_format: str) -> dict:
        normalized_format = str(image_format or "png").strip().lower()
        if normalized_format not in {"png", "jpg", "jpeg"}:
            raise ValueError("image_format invalido. Use png, jpg ou jpeg.")

        image_bytes = pio.to_image(figure, format=normalized_format, width=1400, height=800, scale=2)
        final_name = self._normalize_filename(label, normalized_format)
        stored = save_file_bytes(
            tenant_id=self.tenant_id,
            user_id=self.user_id,
            chat_id=self.session_id,
            filename=final_name,
            content=image_bytes,
            content_type="image/png" if normalized_format == "png" else "image/jpeg",
            kind="chart_export",
            metadata={
                "module_name": self.module_name,
                "agent_name": self.agent_name,
                "label": label,
                "format": normalized_format,
            },
            path_prefix=f"tenants/{self.tenant_id or 'unknown'}/charts/plotly",
        )
        return {
            "id": stored.get("id"),
            "public_url": stored.get("public_url"),
            "format": normalized_format,
        }

    def _ensure_columns(self, dataframe: pd.DataFrame, columns: list[str]) -> None:
        missing = [column for column in columns if column not in dataframe.columns]
        if missing:
            raise ValueError(f"Colunas nao encontradas no resultado: {missing}. Disponiveis: {list(dataframe.columns)}")

    def _normalize_filename(self, value: str, extension: str) -> str:
        base = re.sub(r"[^A-Za-z0-9._-]+", "_", (value or "grafico").strip()).strip("._") or "grafico"
        return f"{base}.{extension}"
