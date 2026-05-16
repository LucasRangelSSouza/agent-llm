from __future__ import annotations

import json
import logging
import os
import re
import tempfile
import time
import traceback
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import boto3
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from botocore.client import Config
from openpyxl import load_workbook
from openpyxl.styles import Font
from prophet import Prophet

import config as settings
from agent.tools.artifact_store import load_dataset_artifact
from agent.tools.sql_query_toolkit import SQLQueryToolkit


logger = logging.getLogger(__name__)

HOLDOUT_RATIO = 0.20
MIN_POINTS_FOR_PROPHET = 12
MOVING_AVERAGE_WINDOW = 3
PROPHET_INTERVAL_WIDTH = 0.80
WINSOR_LOW_Q = 0.02
WINSOR_HIGH_Q = 0.98

PROPHET_GRID: List[Dict[str, Any]] = [
    {"changepoint_prior_scale": 0.05, "seasonality_prior_scale": 5.0, "seasonality_mode": "additive"},
    {"changepoint_prior_scale": 0.10, "seasonality_prior_scale": 5.0, "seasonality_mode": "additive"},
    {"changepoint_prior_scale": 0.20, "seasonality_prior_scale": 5.0, "seasonality_mode": "additive"},
    {"changepoint_prior_scale": 0.05, "seasonality_prior_scale": 10.0, "seasonality_mode": "additive"},
    {"changepoint_prior_scale": 0.10, "seasonality_prior_scale": 10.0, "seasonality_mode": "additive"},
    {"changepoint_prior_scale": 0.20, "seasonality_prior_scale": 10.0, "seasonality_mode": "additive"},
]


def _slugify(text: str) -> str:
    clean = re.sub(r"[^a-zA-Z0-9]+", "_", (text or "").strip().lower())
    return re.sub(r"_+", "_", clean).strip("_") or "forecast"


def _format_ptbr(value: Optional[float]) -> str:
    if value is None:
        return "None"
    try:
        if np.isnan(value) or np.isinf(value):
            return "None"
    except Exception:
        pass
    text = f"{float(value):,.2f}"
    return text.replace(",", "X").replace(".", ",").replace("X", ".")


def _moving_average(values: np.ndarray, window: int) -> np.ndarray:
    arr = np.asarray(values, dtype=float)
    if len(arr) == 0:
        return arr
    output = np.full(len(arr), np.nan, dtype=float)
    window = max(1, int(window))
    for idx in range(len(arr)):
        start = max(0, idx - window + 1)
        output[idx] = float(np.mean(arr[start : idx + 1]))
    return output


def _wape(y_true: np.ndarray, y_pred: np.ndarray, eps: float = 1e-12) -> float:
    return float(np.sum(np.abs(y_true - y_pred)) / (np.sum(np.abs(y_true)) + eps))


def _mae(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    return float(np.mean(np.abs(y_true - y_pred)))


def _smape(y_true: np.ndarray, y_pred: np.ndarray, eps: float = 1e-12) -> float:
    denom = np.abs(y_true) + np.abs(y_pred) + eps
    return float(np.mean(2.0 * np.abs(y_true - y_pred) / denom))


class ForecastToolkit(SQLQueryToolkit):
    """Forecast temporal toolkit baseado em Prophet e no datasource do template."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.storage_client = self._build_storage_client()
        self.storage_bucket = getattr(settings, "FILE_STORAGE_BUCKET", "") or ""
        self.storage_prefix = "artifacts/forecast"
        self.public_base_url = (getattr(settings, "FILE_STORAGE_PUBLIC_ENDPOINT", "") or "").rstrip("/")
        self.url_mode = getattr(settings, "FILE_STORAGE_URL_MODE", "permanent")
        self.url_expires = int(getattr(settings, "FILE_STORAGE_SIGNED_URL_EXPIRES_SECONDS", 86400))

    def generate_forecast(self) -> Callable[..., str]:
        def _tool(
            artifact_url: Optional[str] = None,
            artifact_id: Optional[str] = None,
            granularity: str = "monthly",
            horizon: int = 12,
            label: str = "Forecast",
            date_col: str = "ds",
            value_col: str = "y",
            data: Optional[Any] = None,
            series: Optional[Any] = None,
        ) -> str:
            try:
                payload = {
                    "artifact_url": artifact_url,
                    "artifact_id": artifact_id,
                    "granularity": granularity,
                    "horizon": int(horizon),
                    "label": label,
                    "date_col": date_col,
                    "value_col": value_col,
                    "data": data,
                    "series": series,
                }
                return self._run_forecast_payload(payload)
            except Exception as exc:
                logger.exception("Erro ao executar forecast.")
                return json.dumps({"success": False, "stage": "forecast", "error": str(exc)}, ensure_ascii=False)

        return _tool

    def _run_forecast_payload(self, payload: Dict[str, Any]) -> str:
        date_col = str(payload.get("date_col") or "ds").strip()
        value_col = str(payload.get("value_col") or "y").strip()
        granularity = str(payload.get("granularity") or "monthly").strip()
        horizon = int(payload.get("horizon") or 12)
        label = str(payload.get("label") or "Forecast").strip()

        mode = "direct_data"
        sql = None
        datasource = None
        try:
            if payload.get("artifact_url") or payload.get("artifact_id"):
                mode = "artifact_dataset"
                manifest, dataframe = load_dataset_artifact(
                    artifact_url=payload.get("artifact_url"),
                    artifact_id=payload.get("artifact_id"),
                )
                datasource = {
                    "id": manifest.get("artifact_id"),
                    "name": manifest.get("label"),
                    "kind": "artifact_dataset",
                }
                rows = dataframe.to_dict(orient="records")
            else:
                rows = self._rows_from_payload_data(payload, date_col, value_col)
        except Exception as exc:
            return json.dumps(
                {"success": False, "stage": "input_or_query", "mode": mode, "error": str(exc)},
                ensure_ascii=False,
            )

        if not rows:
            return json.dumps(
                {"success": False, "stage": "data", "mode": mode, "error": "0 linhas/pontos para prever."},
                ensure_ascii=False,
            )

        try:
            series_data, series_meta = self._build_series(rows, date_col, value_col, granularity)
        except Exception as exc:
            return json.dumps(
                {"success": False, "stage": "build_series", "mode": mode, "error": str(exc)},
                ensure_ascii=False,
            )

        ds = pd.to_datetime(series_data.index)
        y = series_data.values.astype(float)
        seasonal_period = self._infer_seasonal_period(self._granularity_to_freq(granularity))
        baselines = self._run_baselines_holdout(y, seasonal_period)
        best_baseline_wape = float(
            min(
                baselines["baseline_last_value"]["wape"],
                baselines["baseline_moving_average"]["wape"],
                baselines["baseline_seasonal"]["wape"],
            )
        )

        try:
            holdout_normal = self._prophet_grid_holdout(ds, y, granularity, use_winsor_train=False)
            holdout_robust = self._prophet_grid_holdout(ds, y, granularity, use_winsor_train=True)
            candidates = []
            if holdout_normal.get("ok") and holdout_normal.get("best"):
                candidates.append((holdout_normal["best"], False))
            if holdout_robust.get("ok") and holdout_robust.get("best"):
                candidates.append((holdout_robust["best"], True))
            if not candidates:
                raise RuntimeError(
                    "Prophet não conseguiu rodar. "
                    f"normal={holdout_normal.get('errors_sample')} robust={holdout_robust.get('errors_sample')}"
                )
            candidates.sort(key=lambda item: float(item[0]["wape"]))
            best, best_use_winsor = candidates[0]
        except Exception as exc:
            return json.dumps(
                {"success": False, "stage": "prophet_holdout", "mode": mode, "error": str(exc)},
                ensure_ascii=False,
            )

        try:
            forecast = self._prophet_fit_and_forecast(
                ds=ds,
                y=y,
                granularity=granularity,
                horizon=horizon,
                best_params=best["params"],
                use_winsor_full_train=best_use_winsor,
            )
        except Exception as exc:
            return json.dumps(
                {"success": False, "stage": "prophet_forecast", "mode": mode, "error": str(exc)},
                ensure_ascii=False,
            )

        artifact_warning = None
        graph_s3_url = None
        graph_http_url = None
        excel_s3_url = None
        excel_http_url = None
        try:
            graph_s3_url, graph_http_url = self._upload_graph(series_data, forecast, label)
            export_df = self._build_export_dataframe(series_data, forecast)
            excel_path = self._write_excel(export_df, label)
            excel_s3_url, excel_http_url = self._upload_excel(excel_path)
        except Exception as exc:
            logger.exception("Forecast artifacts could not be exported.")
            artifact_warning = str(exc)
            graph_s3_url = "not_available"
            graph_http_url = "not_available"
            excel_s3_url = "not_available"
            excel_http_url = "not_available"

        confidence = self._classify_confidence(
            wape_value=float(best["wape"]),
            smape_value=float(best["smape"]),
            baseline_wape=best_baseline_wape,
        )

        report_txt = self._build_report(
            mode=mode,
            granularity=granularity,
            horizon=horizon,
            series_meta=series_meta,
            ds=ds,
            y=y,
            baselines=baselines,
            best=best,
            confidence=confidence,
            graph_s3_url=graph_s3_url,
            graph_http_url=graph_http_url,
            excel_s3_url=excel_s3_url,
            excel_http_url=excel_http_url,
            forecast=forecast,
        )

        output_rows = [{"_meta": {
            "success": True,
            "mode": mode,
            "engine": self._normalize_engine((datasource or {}).get("kind")) if datasource else "artifact_or_data",
            "datasource_id": (datasource or {}).get("id") if datasource else None,
            "datasource_name": (datasource or {}).get("name") if datasource else None,
            "sql_used": sql or None,
            "date_col": date_col,
            "value_col": value_col,
            "granularity": granularity,
            "horizon": horizon,
            "series_meta": series_meta,
            "best_params": best["params"],
            "metrics": {
                "wape": float(best["wape"]),
                "mae": float(best["mae"]),
                "smape": float(best["smape"]),
            },
            "confidence": confidence,
            "graph_s3_url": graph_s3_url,
            "graph_http_url": graph_http_url,
            "excel_s3_url": excel_s3_url,
            "excel_http_url": excel_http_url,
            "artifact_warning": artifact_warning,
            "report_txt": report_txt,
        }}]
        output_rows.extend(self._build_output_rows(series_data, forecast))
        return json.dumps(output_rows, ensure_ascii=False, indent=2)

    def _normalize_forecast_sql(self, sql: str, engine: Optional[str]) -> str:
        query = (sql or "").strip()
        if not query:
            return query
        if engine != "athena":
            return query

        normalized = query
        replacements = [
            (
                r"date_add\(\s*'month'\s*,\s*(-?\d+)\s*,\s*current_date\s*\(\s*\)\s*\)",
                r"date_add('month', \1, date_trunc('day', current_timestamp))",
            ),
            (
                r"date_add\(\s*'month'\s*,\s*(-?\d+)\s*,\s*current_date\b\s*\)",
                r"date_add('month', \1, date_trunc('day', current_timestamp))",
            ),
            (
                r"date_add\(\s*'month'\s*,\s*(-?\d+)\s*,\s*current_date\b",
                r"date_add('month', \1, date_trunc('day', current_timestamp))",
            ),
        ]
        for pattern, replacement in replacements:
            normalized = re.sub(pattern, replacement, normalized, flags=re.IGNORECASE)

        if normalized != query:
            logger.info("Athena SQL normalized for forecast toolkit compatibility.")
        return normalized

    def _load_rows_from_datasource(
        self,
        *,
        sql: str,
        engine: Optional[str],
        datasource_name: Optional[str],
        datasource_id: Optional[str],
        template_key: Optional[str],
        max_rows: int,
    ) -> Tuple[List[Dict[str, Any]], dict]:
        params = self._parse_input(
            sql=sql,
            engine=engine,
            datasource_name=datasource_name,
            datasource_id=datasource_id,
            template_key=template_key,
            max_rows=max_rows,
        )
        template = self._resolve_template(params.get("template_key"))
        datasource = self._select_datasource(
            template=template,
            engine=params.get("engine"),
            datasource_name=params.get("datasource_name") or params.get("datasource") or params.get("database"),
            datasource_id=params.get("datasource_id"),
        )
        if not datasource:
            raise ValueError("Nenhum datasource compatível foi encontrado no template.")
        rows, _, _ = self._execute(datasource, sql, max_rows)
        return rows, datasource

    def _rows_from_payload_data(self, payload: Dict[str, Any], date_col: str, value_col: str) -> List[Dict[str, Any]]:
        data = payload.get("data")
        if isinstance(data, list) and data:
            return data
        series = payload.get("series")
        if isinstance(series, dict):
            ds_arr = series.get(date_col) or series.get("ds")
            y_arr = series.get(value_col) or series.get("y")
            if isinstance(ds_arr, list) and isinstance(y_arr, list) and len(ds_arr) == len(y_arr) and ds_arr:
                return [{date_col: ds_arr[idx], value_col: y_arr[idx]} for idx in range(len(ds_arr))]
        raise ValueError("Você deve fornecer 'sql' ou então 'data'/'series'.")

    def _build_series(
        self,
        rows: List[Dict[str, Any]],
        date_col: str,
        value_col: str,
        granularity: str,
    ) -> Tuple[pd.Series, Dict[str, Any]]:
        df = pd.DataFrame(rows)
        if date_col not in df.columns or value_col not in df.columns:
            raise ValueError(
                f"Colunas não encontradas. Esperado date_col='{date_col}' e value_col='{value_col}'. "
                f"Disponíveis: {list(df.columns)}"
            )

        freq = self._granularity_to_freq(granularity)
        df[date_col] = pd.to_datetime(df[date_col], errors="coerce", utc=False)
        df[value_col] = df[value_col].apply(self._safe_float)
        df = df.dropna(subset=[date_col, value_col])
        if df.empty:
            raise ValueError("Após parse, não sobrou nenhum ponto válido.")

        df[date_col] = self._normalize_period_start(df[date_col], freq)
        grouped = df.groupby(date_col, as_index=True)[value_col].sum(min_count=1).sort_index()
        full_index = pd.date_range(start=grouped.index.min(), end=grouped.index.max(), freq=freq)
        missing_ratio = float(grouped.reindex(full_index).isna().mean())
        grouped = grouped.reindex(full_index).ffill()

        meta = {
            "input_points": int(df.shape[0]),
            "points_after_aggregation": int(grouped.shape[0]),
            "frequency_used": freq,
            "fill_strategy": "ffill",
            "aggregation": "sum",
            "missing_ratio_before_fill": missing_ratio,
            "ds_min": str(grouped.index.min().date()),
            "ds_max": str(grouped.index.max().date()),
            "y_min": float(np.min(grouped.values)),
            "y_max": float(np.max(grouped.values)),
        }
        return grouped.astype(float), meta

    def _run_baselines_holdout(self, y: np.ndarray, seasonal_period: int) -> Dict[str, Any]:
        n = len(y)
        n_test = max(1, int(round(n * HOLDOUT_RATIO)))
        n_train = n - n_test
        y_train = y[:n_train]
        y_true = y[n_train:]
        pred_last = np.full(len(y_true), float(y_train[-1]), dtype=float)
        pred_mm = np.full(len(y_true), float(_moving_average(y_train, MOVING_AVERAGE_WINDOW)[-1]), dtype=float)
        if len(y_train) >= seasonal_period and seasonal_period > 1:
            recent = np.asarray(y_train[-seasonal_period:], dtype=float)
            pred_seasonal = np.array([recent[idx % seasonal_period] for idx in range(len(y_true))], dtype=float)
        else:
            pred_seasonal = pred_last.copy()
        return {
            "seasonal_period": int(seasonal_period),
            "baseline_last_value": {"wape": _wape(y_true, pred_last), "mae": _mae(y_true, pred_last), "smape": _smape(y_true, pred_last)},
            "baseline_moving_average": {"wape": _wape(y_true, pred_mm), "mae": _mae(y_true, pred_mm), "smape": _smape(y_true, pred_mm)},
            "baseline_seasonal": {"wape": _wape(y_true, pred_seasonal), "mae": _mae(y_true, pred_seasonal), "smape": _smape(y_true, pred_seasonal)},
        }

    def _prophet_grid_holdout(
        self,
        ds: pd.DatetimeIndex,
        y: np.ndarray,
        granularity: str,
        use_winsor_train: bool,
    ) -> Dict[str, Any]:
        total_points = int(len(y))
        test_points = max(1, int(round(total_points * HOLDOUT_RATIO)))
        train_points = total_points - test_points
        if total_points < MIN_POINTS_FOR_PROPHET or train_points < MIN_POINTS_FOR_PROPHET:
            return {"ok": False, "best": None, "errors_sample": [], "errors_count": 0}

        ds_train = ds[:train_points]
        y_train = np.asarray(y[:train_points], dtype=float)
        ds_test = ds[train_points:]
        y_true = np.asarray(y[train_points:], dtype=float)
        if use_winsor_train:
            y_train, _ = self._winsorize_train(y_train)

        seasonality = self._prophet_seasonality_flags(granularity)
        best = None
        errors = []
        for params in PROPHET_GRID:
            try:
                model = Prophet(
                    daily_seasonality=seasonality["daily"],
                    weekly_seasonality=seasonality["weekly"],
                    yearly_seasonality=seasonality["yearly"],
                    changepoint_prior_scale=float(params["changepoint_prior_scale"]),
                    seasonality_prior_scale=float(params["seasonality_prior_scale"]),
                    seasonality_mode=str(params["seasonality_mode"]),
                    interval_width=float(PROPHET_INTERVAL_WIDTH),
                )
                model.fit(pd.DataFrame({"ds": ds_train, "y": y_train}))
                prediction = model.predict(pd.DataFrame({"ds": ds_test}))
                y_pred = prediction["yhat"].to_numpy(dtype=float)
                candidate = {
                    "params": params,
                    "wape": _wape(y_true, y_pred),
                    "mae": _mae(y_true, y_pred),
                    "smape": _smape(y_true, y_pred),
                }
                if best is None or float(candidate["wape"]) < float(best["wape"]):
                    best = candidate
            except Exception as exc:
                error_item = {"params": params, "error": str(exc)}
                if bool(int(os.getenv("FORECAST_DEBUG", "0"))):
                    error_item["trace"] = traceback.format_exc()
                errors.append(error_item)
        return {
            "ok": best is not None,
            "best": best,
            "errors_count": len(errors),
            "errors_sample": errors[:2],
        }

    def _prophet_fit_and_forecast(
        self,
        *,
        ds: pd.DatetimeIndex,
        y: np.ndarray,
        granularity: str,
        horizon: int,
        best_params: Dict[str, Any],
        use_winsor_full_train: bool,
    ) -> List[Dict[str, Any]]:
        seasonality = self._prophet_seasonality_flags(granularity)
        freq = self._granularity_to_freq(granularity)
        y_use = np.asarray(y, dtype=float)
        if use_winsor_full_train:
            y_use, _ = self._winsorize_train(y_use)

        model = Prophet(
            daily_seasonality=seasonality["daily"],
            weekly_seasonality=seasonality["weekly"],
            yearly_seasonality=seasonality["yearly"],
            changepoint_prior_scale=float(best_params["changepoint_prior_scale"]),
            seasonality_prior_scale=float(best_params["seasonality_prior_scale"]),
            seasonality_mode=str(best_params["seasonality_mode"]),
            interval_width=float(PROPHET_INTERVAL_WIDTH),
        )
        model.fit(pd.DataFrame({"ds": ds, "y": y_use}))
        future_dates = self._generate_future_dates(pd.Timestamp(ds[-1]), int(horizon), freq)
        prediction = model.predict(pd.DataFrame({"ds": future_dates}))
        return [
            {
                "ds": pd.to_datetime(row["ds"]).strftime("%Y-%m-%d"),
                "yhat": float(row["yhat"]),
                "lo": float(row["yhat_lower"]),
                "hi": float(row["yhat_upper"]),
            }
            for _, row in prediction.iterrows()
        ]

    def _upload_graph(self, series: pd.Series, forecast: List[Dict[str, Any]], label: str) -> Tuple[str, str]:
        hist_ds = pd.to_datetime(series.index)
        hist_y = np.asarray(series.values, dtype=float)
        forecast_df = pd.DataFrame(forecast)
        fut_ds = pd.to_datetime(forecast_df["ds"])
        fut_y = forecast_df["yhat"].astype(float).to_numpy()
        fut_lo = forecast_df["lo"].astype(float).to_numpy()
        fut_hi = forecast_df["hi"].astype(float).to_numpy()

        fig, ax = plt.subplots(figsize=(14, 6))
        ax.plot(hist_ds, hist_y, label="Histórico", linewidth=2.0)
        ax.plot(fut_ds, fut_y, label="Previsão", linewidth=2.0)
        ax.fill_between(fut_ds, fut_lo, fut_hi, alpha=0.20, label="Intervalo")
        ax.set_title(label)
        ax.grid(alpha=0.25)
        ax.legend()
        fig.autofmt_xdate()
        fig.tight_layout()

        with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as tmp:
            local_path = Path(tmp.name)
        try:
            fig.savefig(local_path.as_posix(), dpi=170)
        finally:
            plt.close(fig)

        try:
            remote = self._upload_file(local_path, suffix_path="graphs")
            return remote["s3_url"], remote["http_url"]
        finally:
            local_path.unlink(missing_ok=True)

    def _build_export_dataframe(self, series: pd.Series, forecast: List[Dict[str, Any]]) -> pd.DataFrame:
        hist_ds = pd.to_datetime(series.index)
        hist_y = np.asarray(series.values, dtype=float)
        hist_mm = _moving_average(hist_y, MOVING_AVERAGE_WINDOW)
        history_df = pd.DataFrame(
            {
                "ds": hist_ds,
                "y": hist_y,
                "yhat": [None] * len(hist_ds),
                "lo": [None] * len(hist_ds),
                "hi": [None] * len(hist_ds),
                "moving_average": hist_mm,
                "type": ["history"] * len(hist_ds),
            }
        )
        forecast_df = pd.DataFrame(
            [
                {
                    "ds": pd.to_datetime(item["ds"]),
                    "y": None,
                    "yhat": float(item["yhat"]),
                    "lo": float(item["lo"]),
                    "hi": float(item["hi"]),
                    "moving_average": None,
                    "type": "forecast",
                }
                for item in forecast
            ]
        )
        combined = pd.concat([history_df, forecast_df], ignore_index=True)
        combined["ds"] = pd.to_datetime(combined["ds"], errors="coerce")
        return combined

    def _write_excel(self, df: pd.DataFrame, label: str) -> Path:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp:
            local_path = Path(tmp.name)
        sheet_name = re.sub(r'[:\\/*?\[\]]', "_", label.strip() or "Forecast")[:31] or "Forecast"
        df_to_save = df.copy()
        if "ds" in df_to_save.columns:
            df_to_save["ds"] = pd.to_datetime(df_to_save["ds"], errors="coerce").dt.strftime("%Y-%m-%d")
        with pd.ExcelWriter(local_path.as_posix(), engine="openpyxl") as writer:
            df_to_save.to_excel(writer, index=False, sheet_name=sheet_name)
        workbook = load_workbook(local_path.as_posix())
        worksheet = workbook[sheet_name]
        bold_font = Font(bold=True)
        for cell in worksheet[1]:
            cell.font = bold_font
        for col_cells in worksheet.columns:
            max_length = 0
            column_letter = col_cells[0].column_letter
            for cell in col_cells:
                text = "" if cell.value is None else str(cell.value)
                max_length = max(max_length, len(text))
            worksheet.column_dimensions[column_letter].width = min(max(max_length + 2, 12), 60)
        workbook.save(local_path.as_posix())
        workbook.close()
        return local_path

    def _upload_excel(self, local_path: Path) -> Tuple[str, str]:
        try:
            remote = self._upload_file(local_path, suffix_path="excels")
            return remote["s3_url"], remote["http_url"]
        finally:
            local_path.unlink(missing_ok=True)

    def _build_output_rows(self, series: pd.Series, forecast: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        history_df = pd.DataFrame({"ds": series.index, "y": series.values})
        history_df["type"] = "history"
        history_df["yhat"] = None
        history_df["lo"] = None
        history_df["hi"] = None

        forecast_df = pd.DataFrame(
            [
                {"ds": item["ds"], "y": None, "yhat": item["yhat"], "lo": item["lo"], "hi": item["hi"], "type": "forecast"}
                for item in forecast
            ]
        )
        all_df = pd.concat([history_df, forecast_df], ignore_index=True)
        all_df["ds"] = pd.to_datetime(all_df["ds"], errors="coerce").dt.strftime("%Y-%m-%d")
        return all_df.to_dict(orient="records")

    def _build_report(
        self,
        *,
        mode: str,
        granularity: str,
        horizon: int,
        series_meta: Dict[str, Any],
        ds: pd.DatetimeIndex,
        y: np.ndarray,
        baselines: Dict[str, Any],
        best: Dict[str, Any],
        confidence: Dict[str, Any],
        graph_s3_url: str,
        graph_http_url: str,
        excel_s3_url: str,
        excel_http_url: str,
        forecast: List[Dict[str, Any]],
    ) -> str:
        lines = [
            "FORECAST REPORT",
            "=" * 70,
            "",
            f"RUN | mode={mode} | granularity={granularity} | horizon={horizon}",
            "",
            "SERIES:",
        ]
        for key, value in series_meta.items():
            lines.append(f"- {key}: {value}")
        mm = _moving_average(y, MOVING_AVERAGE_WINDOW)
        lines.extend(["", f"MOVING AVERAGE BASE (window={MOVING_AVERAGE_WINDOW}) | last 6 points:"])
        for current_date, current_value, moving in list(zip(ds.date.astype(str), y, mm))[-6:]:
            lines.append(f"- {current_date}: y={_format_ptbr(current_value)} | ma={_format_ptbr(moving)}")
        lines.extend(["", "HOLDOUT 80/20 (Baselines):", f"- seasonal_period: {baselines['seasonal_period']}"])
        for name in ("baseline_last_value", "baseline_moving_average", "baseline_seasonal"):
            baseline = baselines[name]
            lines.append(
                f"- {name}: wape={baseline['wape']*100:.2f}% | mae={_format_ptbr(baseline['mae'])} | smape={baseline['smape']*100:.2f}%"
            )
        lines.extend(
            [
                "",
                "HOLDOUT 80/20 (Prophet - Best):",
                f"- wape: {best['wape']*100:.2f}%",
                f"- mae: {_format_ptbr(best['mae'])}",
                f"- smape: {best['smape']*100:.2f}%",
                f"- best_params: {best['params']}",
                "",
                "CONFIDENCE:",
                f"- level: {confidence['level']}",
                f"- summary: {confidence['summary']}",
                "",
                "FORECAST:",
            ]
        )
        for item in forecast:
            current_date = pd.to_datetime(item["ds"]).date().isoformat()
            lines.append(
                f"- {current_date}: yhat={_format_ptbr(item['yhat'])} | lo={_format_ptbr(item['lo'])} | hi={_format_ptbr(item['hi'])}"
            )
        lines.extend(
            [
                "",
                "GRAPH (S3):",
                graph_s3_url,
                "",
                "GRAPH (HTTP):",
                graph_http_url,
                "",
                "EXCEL (S3):",
                excel_s3_url,
                "",
                "EXCEL (HTTP):",
                excel_http_url,
                "",
                "=" * 70,
                "END",
            ]
        )
        return "\n".join(lines)

    def _build_storage_client(self):
        endpoint = getattr(settings, "FILE_STORAGE_ENDPOINT", "") or ""
        access_key = getattr(settings, "FILE_STORAGE_ACCESS_KEY", "") or ""
        secret_key = getattr(settings, "FILE_STORAGE_SECRET_KEY", "") or ""
        bucket = getattr(settings, "FILE_STORAGE_BUCKET", "") or ""
        if not endpoint or not access_key or not secret_key or not bucket:
            raise ValueError("FILE_STORAGE_* precisa estar configurado para exportar forecast.")
        return boto3.client(
            "s3",
            endpoint_url=endpoint,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name=getattr(settings, "FILE_STORAGE_REGION", "us-east-1"),
            config=Config(signature_version="s3v4"),
        )

    def _upload_file(self, local_path: Path, *, suffix_path: str) -> Dict[str, str]:
        tenant = _slugify(self.tenant_id or "global")
        module = _slugify(self.module_name or "module")
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        filename = f"{_slugify(local_path.stem)}_{timestamp}{local_path.suffix}"
        object_key = f"{self.storage_prefix}/{tenant}/{module}/{suffix_path}/{filename}"
        self.storage_client.upload_file(local_path.as_posix(), self.storage_bucket, object_key)

        s3_url = f"s3://{self.storage_bucket}/{object_key}"
        if self.url_mode == "permanent" and self.public_base_url:
            http_url = f"{self.public_base_url}/{self.storage_bucket}/{object_key}"
        else:
            http_url = self.storage_client.generate_presigned_url(
                "get_object",
                Params={"Bucket": self.storage_bucket, "Key": object_key},
                ExpiresIn=self.url_expires,
            )
        return {"s3_url": s3_url, "http_url": http_url}

    def _safe_float(self, value: Any) -> Optional[float]:
        if value is None:
            return None
        text = str(value).strip()
        if not text or text.lower() in {"nan", "none", "null"}:
            return None
        if "," in text and "." in text:
            if text.rfind(",") > text.rfind("."):
                text = text.replace(".", "").replace(",", ".")
            else:
                text = text.replace(",", "")
        elif "," in text and "." not in text:
            text = text.replace(",", ".")
        try:
            return float(text)
        except Exception:
            return None

    def _granularity_to_freq(self, granularity: str) -> str:
        normalized = (granularity or "").strip().lower()
        if normalized in {"daily", "diario", "dia", "d"}:
            return "D"
        if normalized in {"weekly", "semanal", "semana", "w"}:
            return "W-MON"
        if normalized in {"monthly", "mensal", "mes", "m"}:
            return "MS"
        if normalized in {"yearly", "anual", "ano", "y"}:
            return "YS"
        raise ValueError("granularity inválida. Use: daily|weekly|monthly|yearly")

    def _normalize_period_start(self, ds: pd.Series, freq: str) -> pd.Series:
        dt = pd.to_datetime(ds, errors="coerce")
        if freq == "D":
            return dt.dt.floor("D")
        if freq.startswith("W"):
            return dt.dt.to_period("W-MON").dt.start_time
        if freq == "MS":
            return dt.dt.to_period("M").dt.to_timestamp(how="start")
        if freq == "YS":
            return dt.dt.to_period("Y").dt.to_timestamp(how="start")
        return dt

    def _generate_future_dates(self, last_ds: pd.Timestamp, periods: int, freq: str) -> pd.DatetimeIndex:
        if freq == "D":
            start = last_ds + pd.Timedelta(days=1)
        elif freq.startswith("W"):
            start = last_ds + pd.Timedelta(days=7)
        elif freq == "MS":
            start = last_ds + pd.offsets.MonthBegin(1)
        elif freq == "YS":
            start = last_ds + pd.offsets.YearBegin(1)
        else:
            start = last_ds + pd.Timedelta(days=1)
        return pd.date_range(start=start, periods=periods, freq=freq)

    def _infer_seasonal_period(self, freq: str) -> int:
        if freq == "D":
            return 7
        if freq.startswith("W"):
            return 52
        if freq == "MS":
            return 12
        if freq == "YS":
            return 1
        return 12

    def _prophet_seasonality_flags(self, granularity: str) -> Dict[str, bool]:
        normalized = (granularity or "").strip().lower()
        if normalized in {"daily", "diario", "dia", "d"}:
            return {"daily": False, "weekly": True, "yearly": True}
        if normalized in {"weekly", "semanal", "semana", "w"}:
            return {"daily": False, "weekly": True, "yearly": True}
        if normalized in {"monthly", "mensal", "mes", "m"}:
            return {"daily": False, "weekly": False, "yearly": True}
        return {"daily": False, "weekly": False, "yearly": False}

    def _winsorize_train(self, y_train: np.ndarray) -> Tuple[np.ndarray, Dict[str, Any]]:
        arr = np.asarray(y_train, dtype=float)
        if len(arr) < 5:
            return arr.copy(), {"ok": False, "reason": "short_train"}
        low = float(np.quantile(arr, WINSOR_LOW_Q))
        high = float(np.quantile(arr, WINSOR_HIGH_Q))
        clipped = np.clip(arr, low, high)
        pct_clip = float(np.mean((arr < low) | (arr > high))) if len(arr) else 0.0
        return clipped, {"ok": True, "lo": low, "hi": high, "pct_clip": pct_clip}

    def _classify_confidence(self, *, wape_value: float, smape_value: float, baseline_wape: float) -> Dict[str, str]:
        if wape_value < 0.25:
            level = "Excellent"
        elif wape_value < 0.40:
            level = "Good"
        elif wape_value <= 0.60:
            level = "Medium"
        else:
            level = "Poor"
        delta_pp = (wape_value - baseline_wape) * 100.0
        if delta_pp < -1e-9:
            comparison = f"better than the baseline by {abs(delta_pp):.2f} p.p."
        elif delta_pp > 1e-9:
            comparison = f"worse than the baseline by {abs(delta_pp):.2f} p.p."
        else:
            comparison = "tied with the baseline"
        return {
            "level": level,
            "summary": f"Classification based on WAPE={wape_value*100:.2f}% and sMAPE={smape_value*100:.2f}%; result is {comparison}.",
        }
