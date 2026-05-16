# sql_previsao_toolkit.py
# -*- coding: utf-8 -*-

"""
PrevisivoAthenaToolKit (FINAL - Prophet + gráfico em S3 com link HTTP)
=====================================================================

- Entrada: SQL (Athena) ou dados diretos (data/series)
- Monta série (granularity: daily|weekly|monthly|yearly)
- Sempre:
  - agregação = sum
  - preenchimento = ffill
- Roda mini-grid Prophet (6 combinações) + disputa com modo robusto (winsor só no treino)
- Escolhe o MELHOR global pelo holdout 80/20 (WAPE)
- Gera gráfico (Histórico + Previsão) e faz upload no S3 (GRAPHS_S3_BASE)
- Gera também um link HTTP (presigned URL) do PNG para você abrir direto no navegador
- Saída:
  - JSON com _meta (inclui report_txt, graph_s3_url e graph_http_url)
  - history + forecast
"""

import os
import re
import time
import json
import logging
from typing import Any, List, Dict, Optional, Callable, Tuple, Union

import boto3
from botocore.exceptions import ClientError

import pandas as pd
import numpy as np
import traceback
from openpyxl import load_workbook
from openpyxl.styles import Font

try:
    from prophet import Prophet  # type: ignore
except Exception as e:
    raise ImportError(
        "Dependências ausentes. Instale: prophet (e cmdstanpy). "
        f"Erro original: {e}"
    )

logger = logging.getLogger(__name__)

# =============================================================================
# CONSTANTES (chumbadas, simples)
# =============================================================================

HOLDOUT_RATIO = 0.20
MIN_PONTOS_PARA_PROPHET = 12

AGGREGACAO = "sum"
PREENCHIMENTO = "ffill"

WINSOR_LOW_Q = 0.02
WINSOR_HIGH_Q = 0.98

JANELA_MEDIA_MOVEL = 3

PROPHET_INTERVAL_WIDTH = 0.80  # 80% (lo/hi)

PROPHET_GRID: List[Dict[str, Any]] = [
    {"changepoint_prior_scale": 0.05, "seasonality_prior_scale": 5.0,  "seasonality_mode": "additive"},
    {"changepoint_prior_scale": 0.10, "seasonality_prior_scale": 5.0,  "seasonality_mode": "additive"},
    {"changepoint_prior_scale": 0.20, "seasonality_prior_scale": 5.0,  "seasonality_mode": "additive"},
    {"changepoint_prior_scale": 0.05, "seasonality_prior_scale": 10.0, "seasonality_mode": "additive"},
    {"changepoint_prior_scale": 0.10, "seasonality_prior_scale": 10.0, "seasonality_mode": "additive"},
    {"changepoint_prior_scale": 0.20, "seasonality_prior_scale": 10.0, "seasonality_mode": "additive"},
]


# =============================================================================
# Helpers: métricas, formatação, utilitários
# =============================================================================

def _fmt_ptbr(v: Optional[float]) -> str:
    """Formata número no padrão PT-BR com 2 casas."""
    if v is None:
        return "None"
    try:
        if np.isnan(v) or np.isinf(v):
            return "None"
    except Exception:
        pass
    s = f"{float(v):,.2f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")

def _wape(y_true: np.ndarray, y_pred: np.ndarray, eps: float = 1e-12) -> float:
    """WAPE = sum(|err|) / sum(|y|)."""
    y_true = np.asarray(y_true, dtype=float)
    y_pred = np.asarray(y_pred, dtype=float)
    denom = float(np.sum(np.abs(y_true)) + eps)
    return float(np.sum(np.abs(y_true - y_pred)) / denom)

def _mae(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    """MAE."""
    y_true = np.asarray(y_true, dtype=float)
    y_pred = np.asarray(y_pred, dtype=float)
    return float(np.mean(np.abs(y_true - y_pred)))

def _smape(y_true: np.ndarray, y_pred: np.ndarray, eps: float = 1e-12) -> float:
    """sMAPE em fração (no TXT mostramos em %)."""
    y_true = np.asarray(y_true, dtype=float)
    y_pred = np.asarray(y_pred, dtype=float)
    denom = np.abs(y_true) + np.abs(y_pred) + eps
    return float(np.mean(2.0 * np.abs(y_true - y_pred) / denom))

def _media_movel(valores: np.ndarray, janela: int) -> np.ndarray:
    """Média móvel simples (SMA)."""
    v = np.asarray(valores, dtype=float)
    if len(v) == 0:
        return v
    janela = int(max(1, janela))
    out = np.full(len(v), np.nan, dtype=float)
    for i in range(len(v)):
        j0 = max(0, i - janela + 1)
        out[i] = float(np.mean(v[j0:i + 1]))
    return out

def _classificar_confianca(wape_val: float, smape_val: float, wape_baseline_ref: float) -> Tuple[str, str]:
    """
    Classificação simples e prática.
    Ajuste depois se quiser, mas já entrega um “Ótimo/Bom/Médio/Ruim”.
    """
    if wape_val < 0.25:
        level = "Ótimo"
    elif wape_val < 0.40:
        level = "Bom"
    elif wape_val <= 0.60:
        level = "Médio"
    else:
        level = "Ruim"

    delta_pp = (wape_val - wape_baseline_ref) * 100.0
    if delta_pp < -1e-9:
        comp = f"melhor que o baseline de referência em {abs(delta_pp):.2f} p.p."
    elif delta_pp > 1e-9:
        comp = f"pior que o baseline de referência em {abs(delta_pp):.2f} p.p."
    else:
        comp = "empatado com o baseline de referência"

    summary = (
        f"Classificação baseada em WAPE={wape_val*100:.2f}% e sMAPE={smape_val*100:.2f}%; resultado {comp}."
    )
    return level, summary

def _granularity_to_freq(granularity: str) -> str:
    g = (granularity or "").strip().lower()
    if g in ("daily", "diario", "dia", "d"):
        return "D"
    if g in ("weekly", "semanal", "semana", "w"):
        return "W-MON"
    if g in ("monthly", "mensal", "mes", "m"):
        return "MS"
    if g in ("yearly", "anual", "ano", "y"):
        return "YS"
    raise ValueError("granularity inválida. Use: daily|weekly|monthly|yearly")

def _normalizar_inicio_periodo(ds: pd.Series, freq: str) -> pd.Series:
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

def _gerar_datas_futuras(last_ds: pd.Timestamp, periods: int, freq: str) -> pd.DatetimeIndex:
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

def _split_s3_uri(s3_uri: str) -> Tuple[str, str]:
    s3_uri = s3_uri.strip()
    if not s3_uri.startswith("s3://"):
        raise ValueError(f"URI S3 inválida: {s3_uri}")
    no_scheme = s3_uri.replace("s3://", "", 1)
    parts = no_scheme.split("/", 1)
    bucket = parts[0]
    prefix = parts[1] if len(parts) > 1 else ""
    return bucket, prefix

def _slugify(texto: str) -> str:
    texto = (texto or "").strip().lower()
    texto = re.sub(r"[^a-z0-9]+", "_", texto)
    texto = re.sub(r"_+", "_", texto).strip("_")
    return texto or "grafico"

def _sheet_name(label: str) -> str:
    """
    Excel limita sheet name a 31 caracteres e não permite alguns caracteres.
    """
    name = (label or "Planilha").strip()
    name = re.sub(r'[:\\/*?\[\]]', "_", name)
    name = name[:31].strip()
    return name or "Planilha"


# =============================================================================
# Classe principal
# =============================================================================

class PrevisivoAthenaToolKit:
    """
    Tool de previsão com Prophet + Athena (opcional), com gráfico em S3 e URL HTTP presigned.

    Variáveis de ambiente esperadas (você disse que já tem):
    - GRAPHS_S3_BASE
    - ATHENA_OUTPUT_LOCATION
    - AWS_ACCESS_KEY_ID
    - AWS_SECRET_ACCESS_KEY
    - AWS_DEFAULT_REGION

    Obs:
    - athena_database pode vir por parâmetro (ou você setar em outro lugar do seu projeto).
    """

    def __init__(
        self,
        athena_database: Optional[str] = None,
        graphs_s3_base: Optional[str] = None,
        excel_s3_base: Optional[str] = None,
        athena_output_location: Optional[str] = None,
        region_name: Optional[str] = None,
        aws_access_key_id: Optional[str] = None,
        aws_secret_access_key: Optional[str] = None,
        aws_session_token: Optional[str] = None,
        poll_interval: int = 2,
        max_rows: int = 200000,
        presign_expires_seconds: int = 604800,
        
    ) -> None:
        """
        Inicializa clientes AWS.
        - Usa env vars por padrão (como referência), mas permite override por parâmetro.
        - presign_expires_seconds: validade do link HTTP (1h por padrão).
        """
        self.region_name = region_name or "us-east-1"
        self.aws_access_key_id = aws_access_key_id or ""
        self.aws_secret_access_key = aws_secret_access_key or ""
        self.aws_session_token = aws_session_token or ""
        self.excel_s3_base = excel_s3_base or ""
        self.athena_database = athena_database or ""  # se você usar SQL, precisa setar
        self.athena_output_location = athena_output_location or ""
        self.graphs_s3_base = graphs_s3_base or ""

        self.poll_interval = int(poll_interval)
        self.max_rows = int(max_rows)
        self.presign_expires_seconds = int(presign_expires_seconds)

        if not self.aws_access_key_id or not self.aws_secret_access_key:
            raise ValueError("Credenciais AWS ausentes (AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY).")
        if not self.graphs_s3_base:
            raise ValueError("GRAPHS_S3_BASE ausente.")
        if not self.graphs_s3_base.startswith("s3://"):
            raise ValueError("GRAPHS_S3_BASE deve ser s3://bucket/prefix/")
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
        self.debug = bool(int(os.getenv("PREVISAO_DEBUG", "0")))
        # reduz spam do cmdstanpy nos logs
        logging.getLogger("cmdstanpy").setLevel(logging.WARNING)

        logger.info(
            "[PrevisivoAthenaToolKit] Inicializado | Região=%s | AthenaOutput=%s | GraphsBase=%s | ExcelBase=%s",
            self.region_name, self.athena_output_location, self.graphs_s3_base, self.excel_s3_base
        )

        

    # -------------------------------------------------------------------------
    # Athena
    # -------------------------------------------------------------------------

    def _ensure_athena_output_bucket_if_needed(self) -> None:
        """
        Garante que o bucket de ATHENA_OUTPUT_LOCATION exista (se você usar modo SQL).
        Se ATHENA_OUTPUT_LOCATION estiver vazio, não faz nada.
        """
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

    @staticmethod
    def _extract_bucket_name(s3_uri: str) -> str:
        if not s3_uri.startswith("s3://"):
            raise ValueError(f"S3 URI inválida: {s3_uri}")
        return s3_uri.replace("s3://", "", 1).split("/", 1)[0]

    def _execute_athena_query(self, query: str) -> List[Dict[str, Any]]:
        """
        Executa query no Athena e retorna lista de dicts.
        Guardrail: max_rows.
        """
        if not isinstance(query, str) or not query.strip():
            raise ValueError("Nenhuma consulta SQL válida foi fornecida.")
        if not self.athena_database:
            raise ValueError("athena_database não configurado (necessário para modo SQL).")
        if not self.athena_output_location:
            raise ValueError("ATHENA_OUTPUT_LOCATION não configurado (necessário para modo SQL).")

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
                        "Agregue mais no SQL (ex.: por mês) antes de prever."
                    )

        return rows

    # -------------------------------------------------------------------------
    # Série
    # -------------------------------------------------------------------------

    @staticmethod
    def _safe_float(x: Any) -> Optional[float]:
        """Converte para float com heurística PT/EN."""
        if x is None:
            return None
        s = str(x).strip()
        if s == "" or s.lower() in ("nan", "none", "null"):
            return None

        if "," in s and "." in s:
            if s.rfind(",") > s.rfind("."):
                s = s.replace(".", "").replace(",", ".")
            else:
                s = s.replace(",", "")
        else:
            if "," in s and "." not in s:
                s = s.replace(",", ".")

        try:
            return float(s)
        except Exception:
            return None

    def _rows_from_payload_data(self, payload: Dict[str, Any], date_col: str, value_col: str) -> List[Dict[str, Any]]:
        """Converte payload["data"] ou payload["series"] em rows."""
        if "data" in payload and payload["data"] is not None:
            data = payload["data"]
            if not isinstance(data, list) or len(data) == 0:
                raise ValueError("Campo 'data' deve ser lista não-vazia.")
            for i, item in enumerate(data):
                if not isinstance(item, dict):
                    raise ValueError(f"'data[{i}]' deve ser dict.")
            return data

        if "series" in payload and payload["series"] is not None:
            s = payload["series"]
            if not isinstance(s, dict):
                raise ValueError("Campo 'series' deve ser {'ds':[...], 'y':[...]}.")

            ds_arr = s.get(date_col) or s.get("ds")
            y_arr = s.get(value_col) or s.get("y")
            if not isinstance(ds_arr, list) or not isinstance(y_arr, list) or len(ds_arr) == 0:
                raise ValueError("Em 'series', forneça arrays não-vazios.")
            if len(ds_arr) != len(y_arr):
                raise ValueError("Em 'series', datas e valores devem ter mesmo tamanho.")

            return [{date_col: ds_arr[i], value_col: y_arr[i]} for i in range(len(ds_arr))]

        raise ValueError("Você deve fornecer 'sql' OU ('data' / 'series').")

    def _build_series(
        self,
        rows: List[Dict[str, Any]],
        date_col: str,
        value_col: str,
        granularity: str,
    ) -> Tuple[pd.Series, Dict[str, Any]]:
        """Monta série contínua (sum + ffill) conforme granularidade."""
        df = pd.DataFrame(rows)
        if date_col not in df.columns or value_col not in df.columns:
            raise ValueError(
                f"Colunas não encontradas. Esperado date_col='{date_col}' e value_col='{value_col}'. "
                f"Disponíveis: {list(df.columns)}"
            )

        freq = _granularity_to_freq(granularity)

        df[date_col] = pd.to_datetime(df[date_col], errors="coerce", utc=False)
        df[value_col] = df[value_col].apply(self._safe_float)

        df = df.dropna(subset=[date_col, value_col])
        if df.empty:
            raise ValueError("Após parse, não sobrou nenhum ponto válido.")

        df[date_col] = _normalizar_inicio_periodo(df[date_col], freq)

        # sempre sum
        g = df.groupby(date_col, as_index=True)[value_col].sum(min_count=1).sort_index()

        idx = pd.date_range(start=g.index.min(), end=g.index.max(), freq=freq)
        missing_ratio = float(g.reindex(idx).isna().mean())

        g = g.reindex(idx)

        # sempre ffill
        g = g.ffill()

        meta = {
            "pontos_entrada": int(df.shape[0]),
            "pontos_apos_agregacao": int(g.shape[0]),
            "frequencia_usada": freq,
            "preenchimento_faltantes": PREENCHIMENTO,
            "agregacao": AGGREGACAO,
            "proporcao_faltantes_antes_preencher": missing_ratio,
            "ds_min": str(g.index.min().date()),
            "ds_max": str(g.index.max().date()),
            "y_min": float(np.min(g.values)),
            "y_max": float(np.max(g.values)),
        }
        return g.astype(float), meta

    # -------------------------------------------------------------------------
    # Baselines
    # -------------------------------------------------------------------------

    @staticmethod
    def _infer_seasonal_period(freq: str) -> int:
        f = (freq or "").upper()
        if f == "MS":
            return 12
        if f.startswith("W"):
            return 52
        if f == "D":
            return 7
        if f == "YS":
            return 1
        return 1

    def _run_baselines_holdout(self, y: np.ndarray, seasonal_period: int) -> Dict[str, Any]:
        """Baselines no holdout 80/20."""
        n = len(y)
        n_test = max(1, int(round(n * HOLDOUT_RATIO)))
        n_train = n - n_test

        y_train = y[:n_train]
        y_true = y[n_train:]

        pred_last = np.full(len(y_true), float(y_train[-1]), dtype=float)

        mm = _media_movel(y_train, JANELA_MEDIA_MOVEL)
        pred_mm = np.full(len(y_true), float(mm[-1]), dtype=float)

        if len(y_train) >= seasonal_period and seasonal_period > 1:
            ult = np.asarray(y_train[-seasonal_period:], dtype=float)
            pred_seas = np.array([ult[i % seasonal_period] for i in range(len(y_true))], dtype=float)
        else:
            pred_seas = pred_last.copy()

        return {
            "seasonal_period": int(seasonal_period),
            "baseline_ultimo_valor": {"wape": _wape(y_true, pred_last), "mae": _mae(y_true, pred_last), "smape": _smape(y_true, pred_last)},
            "baseline_media_movel": {"wape": _wape(y_true, pred_mm), "mae": _mae(y_true, pred_mm), "smape": _smape(y_true, pred_mm)},
            "baseline_sazonal": {"wape": _wape(y_true, pred_seas), "mae": _mae(y_true, pred_seas), "smape": _smape(y_true, pred_seas)},
        }

    # -------------------------------------------------------------------------
    # Prophet
    # -------------------------------------------------------------------------

    @staticmethod
    def _prophet_seasonality_flags(granularity: str) -> Dict[str, bool]:
        """Sazonalidades (simples e rápidas)."""
        g = (granularity or "").strip().lower()
        daily = False
        weekly = False
        yearly = False

        if g in ("daily", "diario", "dia", "d"):
            weekly = True
            yearly = True
        elif g in ("weekly", "semanal", "semana", "w"):
            weekly = True
            yearly = True
        elif g in ("monthly", "mensal", "mes", "m"):
            yearly = True
        elif g in ("yearly", "anual", "ano", "y"):
            yearly = False

        return {"daily": daily, "weekly": weekly, "yearly": yearly}

    def _winsorize_train(self, y_train: np.ndarray) -> Tuple[np.ndarray, Dict[str, Any]]:
        """Winsoriza extremos do treino (só para disputa)."""
        yt = np.asarray(y_train, dtype=float)
        if len(yt) < 5:
            return yt.copy(), {"ok": False, "motivo": "treino_curto"}

        lo = float(np.quantile(yt, WINSOR_LOW_Q))
        hi = float(np.quantile(yt, WINSOR_HIGH_Q))
        y2 = np.clip(yt, lo, hi)
        pct_clip = float(np.mean((yt < lo) | (yt > hi))) if len(yt) else 0.0
        return y2, {"ok": True, "low_q": WINSOR_LOW_Q, "high_q": WINSOR_HIGH_Q, "lo": lo, "hi": hi, "pct_clip": pct_clip}

    def _prophet_grid_holdout(
            self,
            ds: pd.DatetimeIndex,
            y: np.ndarray,
            granularity: str,
            use_winsor_train: bool,
        ) -> Dict[str, Any]:
            """
            Roda grid e retorna o melhor por WAPE no holdout 80/20.

            Correções principais:
            - NÃO engole exceções: coleta erros por parâmetro
            - Retorna amostra de erros (com stacktrace opcional via self.debug)
            - Mantém o comportamento de escolher o melhor por WAPE
            """
            import traceback  # local para não “poluir” imports do módulo

            n = int(len(y))
            n_test = max(1, int(round(n * HOLDOUT_RATIO)))
            n_train = n - n_test

            meta = {
                "n_total": n,
                "n_train": n_train,
                "n_test": n_test,
                "holdout_ratio": HOLDOUT_RATIO,
                "use_winsor_train": bool(use_winsor_train),
            }

            # Guardrails: série mínima
            if n < MIN_PONTOS_PARA_PROPHET or n_train < MIN_PONTOS_PARA_PROPHET:
                return {
                    "ok": False,
                    "motivo": "serie_curta_demais_para_prophet",
                    "meta": meta,
                    "best": None,
                    "errors_count": 0,
                    "errors_sample": [],
                }

            # Split
            ds_train = ds[:n_train]
            y_train = np.asarray(y[:n_train], dtype=float)
            ds_test = ds[n_train:]
            y_true = np.asarray(y[n_train:], dtype=float)

            # Winsor no treino (opcional)
            if use_winsor_train:
                y_train_use, wins_meta = self._winsorize_train(y_train)
                meta["winsor"] = wins_meta
            else:
                y_train_use = y_train

            # Sazonalidades
            saz = self._prophet_seasonality_flags(granularity)

            best: Optional[Dict[str, Any]] = None
            errors: List[Dict[str, Any]] = []

            # Grid search
            for params in PROPHET_GRID:
                try:
                    m = Prophet(
                        daily_seasonality=bool(saz["daily"]),
                        weekly_seasonality=bool(saz["weekly"]),
                        yearly_seasonality=bool(saz["yearly"]),
                        changepoint_prior_scale=float(params["changepoint_prior_scale"]),
                        seasonality_prior_scale=float(params["seasonality_prior_scale"]),
                        seasonality_mode=str(params["seasonality_mode"]),
                        interval_width=float(PROPHET_INTERVAL_WIDTH),
                    )

                    m.fit(pd.DataFrame({"ds": ds_train, "y": y_train_use}))

                    pred = m.predict(pd.DataFrame({"ds": ds_test}))
                    if "yhat" not in pred.columns:
                        raise RuntimeError("Prophet.predict não retornou coluna 'yhat'.")

                    y_pred = pred["yhat"].to_numpy(dtype=float)

                    cand = {
                        "params": params,
                        "wape": _wape(y_true, y_pred),
                        "mae": _mae(y_true, y_pred),
                        "smape": _smape(y_true, y_pred),
                    }

                    if best is None or float(cand["wape"]) < float(best["wape"]):
                        best = cand

                except Exception as e:
                    # Guarda erro por combinação do grid
                    err_item: Dict[str, Any] = {
                        "params": params,
                        "error": str(e),
                    }
                    if bool(getattr(self, "debug", False)):
                        err_item["trace"] = traceback.format_exc()
                    errors.append(err_item)
                    continue

            # Se nenhuma combinação funcionou, devolve amostra de erros
            if best is None:
                return {
                    "ok": False,
                    "motivo": "grid_sem_resultados_validos",
                    "meta": meta,
                    "best": None,
                    "errors_count": len(errors),
                    "errors_sample": errors[:2],  # evita JSON gigante
                }

            return {
                "ok": True,
                "motivo": None,
                "meta": meta,
                "best": best,
                "errors_count": len(errors),
                "errors_sample": errors[:2] if errors else [],
            }

    def _prophet_fit_and_forecast(
        self,
        ds: pd.DatetimeIndex,
        y: np.ndarray,
        granularity: str,
        horizon: int,
        best_params: Dict[str, Any],
        use_winsor_full_train: bool,
    ) -> List[Dict[str, Any]]:
        """Treina na série completa e gera previsão futura."""
        saz = self._prophet_seasonality_flags(granularity)
        freq = _granularity_to_freq(granularity)

        y_use = y
        if use_winsor_full_train:
            y_use, _ = self._winsorize_train(y_use)

        m = Prophet(
            daily_seasonality=saz["daily"],
            weekly_seasonality=saz["weekly"],
            yearly_seasonality=saz["yearly"],
            changepoint_prior_scale=float(best_params["changepoint_prior_scale"]),
            seasonality_prior_scale=float(best_params["seasonality_prior_scale"]),
            seasonality_mode=str(best_params["seasonality_mode"]),
            interval_width=PROPHET_INTERVAL_WIDTH,
        )
        m.fit(pd.DataFrame({"ds": ds, "y": y_use}))

        future_ds = _gerar_datas_futuras(pd.to_datetime(ds[-1]), periods=int(horizon), freq=freq)
        fc = m.predict(pd.DataFrame({"ds": future_ds}))

        forecast: List[Dict[str, Any]] = []
        for i in range(len(fc)):
            forecast.append({
                "ds": pd.to_datetime(fc.iloc[i]["ds"]),
                "yhat": float(fc.iloc[i]["yhat"]),
                "lo": float(fc.iloc[i]["yhat_lower"]),
                "hi": float(fc.iloc[i]["yhat_upper"]),
            })
        return forecast

    # -------------------------------------------------------------------------
    # Gráfico + S3 + HTTP (presigned)
    # -------------------------------------------------------------------------

    def _upload_graph_s3_and_presign(
        self,
        series: pd.Series,
        forecast: List[Dict[str, Any]],
        label: str,
    ) -> Tuple[str, str]:
        """
        - Gera PNG (Histórico + Previsão)
        - Figura maior (mais larga e mais alta)
        - Sem notação científica e sem offset (remove "1e6")
        - Mostra valor em cada ponto (com fundo branco leve)
        - Linha simples de tendência (média móvel)
        - Faz upload no S3
        - Gera presigned URL HTTP
        Retorna: (graph_s3_url, graph_http_url)
        """
        import matplotlib.pyplot as plt
        import matplotlib.ticker as mticker

        # -----------------------------
        # Dados
        # -----------------------------
        hist_ds = pd.to_datetime(series.index)
        hist_y = np.asarray(series.values, dtype=float)

        fut_ds = [pd.to_datetime(r["ds"]) for r in forecast]
        fut_y = np.asarray([float(r["yhat"]) for r in forecast], dtype=float)

        # Tendência simples (média móvel)
        try:
            trend_y = _media_movel(hist_y, JANELA_MEDIA_MOVEL)
        except Exception:
            trend_y = None

        # -----------------------------
        # Helpers
        # -----------------------------
        def _fmt_int_ptbr(x: Any) -> str:
            try:
                v = float(x)
                if np.isnan(v) or np.isinf(v):
                    return ""
            except Exception:
                return ""
            s = f"{int(round(v)):,}"
            return s.replace(",", ".")

        # Rotular todos os pontos pode poluir se tiver MUITOS.
        # Aqui é "agressivo" (quase sempre rotula tudo), mas com um guardrail mínimo.
        def _label_step(n_points: int) -> int:
            if n_points <= 36:
                return 1
            if n_points <= 72:
                return 2
            if n_points <= 144:
                return 3
            return 4

        # -----------------------------
        # Plot (figura maior)
        # -----------------------------
        fig, ax = plt.subplots(figsize=(14, 8))  # <- maior em todos os eixos

        ax.plot(hist_ds, hist_y, marker="o", label="Histórico", zorder=3)
        ax.plot(fut_ds, fut_y, marker="o", label="Previsão", zorder=3)

        if trend_y is not None and len(trend_y) == len(hist_y):
            ax.plot(hist_ds, trend_y, label=f"Tendência (MM{int(JANELA_MEDIA_MOVEL)})", zorder=2)

        ax.set_title(label)
        ax.set_xlabel("Data")
        ax.set_ylabel("Valor")

        # Dá respiro pra caber os textos dos rótulos sem cortar
        ax.margins(x=0.02, y=0.18)

        # -----------------------------
        # Eixo Y: SEM notação científica e SEM offset ("1e6")
        # -----------------------------
        ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, pos: _fmt_int_ptbr(x)))

        # desliga scientific/offset de vez
        try:
            ax.ticklabel_format(axis="y", style="plain", useOffset=False)
        except Exception:
            pass
        try:
            ax.yaxis.get_offset_text().set_visible(False)
        except Exception:
            pass

        # -----------------------------
        # Rótulos nos pontos (valor em cada ponto)
        # -----------------------------
        def _annotate_points(dates, values):
            n = len(values)
            if n == 0:
                return
            step = _label_step(n)

            for i, (d, v) in enumerate(zip(dates, values)):
                if i % step != 0:
                    continue
                try:
                    if v is None or np.isnan(v) or np.isinf(v):
                        continue
                except Exception:
                    continue

                ax.annotate(
                    _fmt_int_ptbr(v),
                    (d, v),
                    textcoords="offset points",
                    xytext=(0, 10),
                    ha="center",
                    va="bottom",
                    fontsize=9,
                    zorder=10,
                    clip_on=False,          # <- não recorta no limite do eixo
                    annotation_clip=False,  # <- garante render fora do eixo
                    bbox=dict(              # <- fundinho pra enxergar em cima da linha
                        boxstyle="round,pad=0.2",
                        fc="white",
                        ec="none",
                        alpha=0.7
                    ),
                )

        _annotate_points(hist_ds, hist_y)
        _annotate_points(fut_ds, fut_y)

        ax.legend()
        fig.autofmt_xdate()

        # Ajusta layout (sem cortar)
        fig.tight_layout()

        # -----------------------------
        # Salvar local
        # -----------------------------
        ts = time.strftime("%Y%m%d_%H%M%S")
        fname = f"{_slugify(label)}_{ts}.png"
        local_path = os.path.join(os.getcwd(), fname)

        fig.savefig(local_path, dpi=170)  # dpi um pouco maior pra ficar bem legível
        plt.close(fig)

        # -----------------------------
        # Upload S3 + presign
        # -----------------------------
        bucket, base_prefix = _split_s3_uri(self.graphs_s3_base)
        key = base_prefix.rstrip("/") + "/" + fname if base_prefix else fname

        self.s3_client.upload_file(local_path, bucket, key)

        try:
            os.remove(local_path)
        except Exception:
            pass

        graph_s3_url = f"s3://{bucket}/{key}"

        graph_http_url = self.s3_client.generate_presigned_url(
            ClientMethod="get_object",
            Params={"Bucket": bucket, "Key": key},
            ExpiresIn=self.presign_expires_seconds,
        )

        return graph_s3_url, graph_http_url


    def _build_export_dataframe(
        self,
        series: pd.Series,
        forecast: List[Dict[str, Any]],
    ) -> pd.DataFrame:
        """
        Monta DataFrame final do Excel com:
        - histórico + previsão
        - type = history / forecast
        - média móvel
        - lo/hi nas previsões
        """
        hist_ds = pd.to_datetime(series.index)
        hist_y = np.asarray(series.values, dtype=float)
        hist_mm = _media_movel(hist_y, JANELA_MEDIA_MOVEL)

        hist_df = pd.DataFrame({
            "ds": hist_ds,
            "y": hist_y,
            "yhat": [None] * len(hist_ds),
            "lo": [None] * len(hist_ds),
            "hi": [None] * len(hist_ds),
            "media_movel": hist_mm,
            "type": ["history"] * len(hist_ds),
        })

        fc_df = pd.DataFrame([{
            "ds": pd.to_datetime(r["ds"]),
            "y": None,
            "yhat": float(r["yhat"]),
            "lo": float(r["lo"]),
            "hi": float(r["hi"]),
            "media_movel": None,
            "type": "forecast",
        } for r in forecast])

        export_df = pd.concat([hist_df, fc_df], ignore_index=True)
        export_df["ds"] = pd.to_datetime(export_df["ds"], errors="coerce")

        return export_df

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
        safe_file_name = _slugify(label)
        file_name = f"{safe_file_name}_{ts}.xlsx"
        local_path = os.path.join(os.getcwd(), file_name)

        sheet_name = _sheet_name(label)

        df_to_save = df.copy()
        if "ds" in df_to_save.columns:
            df_to_save["ds"] = pd.to_datetime(df_to_save["ds"], errors="coerce").dt.strftime("%Y-%m-%d")

        with pd.ExcelWriter(local_path, engine="openpyxl") as writer:
            df_to_save.to_excel(writer, index=False, sheet_name=sheet_name)

        wb = load_workbook(local_path)
        ws = wb[sheet_name]

        bold_font = Font(bold=True)
        for cell in ws[1]:
            cell.font = bold_font

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
    
    def _upload_excel_s3_and_presign(self, local_path: str) -> Tuple[str, str]:
        bucket, base_prefix = _split_s3_uri(self.excel_s3_base)
        file_name = os.path.basename(local_path)
        key = base_prefix.rstrip("/") + "/" + file_name if base_prefix else file_name

        self.s3_client.upload_file(local_path, bucket, key)

        try:
            os.remove(local_path)
        except Exception:
            pass

        excel_s3_url = f"s3://{bucket}/{key}"

        excel_http_url = self.s3_client.generate_presigned_url(
            ClientMethod="get_object",
            Params={"Bucket": bucket, "Key": key},
            ExpiresIn=self.presign_expires_seconds,
        )

        return excel_s3_url, excel_http_url


    # -------------------------------------------------------------------------
    # TXT
    # -------------------------------------------------------------------------

    def _build_report_txt(
        self,
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

        """Monta seu relatório TXT, incluindo a lista completa da previsão futura."""
        lines: List[str] = []
        lines.append("AVALIAÇÃO TEXTUAL (LLM-friendly)")
        lines.append("=" * 70)
        lines.append("")
        lines.append(f"TESTE | modo={mode} | granularidade={granularity} | horizonte={horizon}")
        lines.append("")

        lines.append("SERIE:")
        for k, v in series_meta.items():
            lines.append(f"- {k}: {v}")

        mm = _media_movel(y, JANELA_MEDIA_MOVEL)
        lines.append("")
        lines.append(f"MEDIA_MOVEL_BASE (SMA janela={JANELA_MEDIA_MOVEL}) | últimos 6 pontos:")
        for d, yy, m in list(zip(ds.date.astype(str), y, mm))[-6:]:
            lines.append(f"- {d}: y={_fmt_ptbr(yy)} | mm={_fmt_ptbr(m)}")

        lines.append("")
        lines.append("HOLDOUT 80/20 (Baselines):")
        lines.append(f"- seasonal_period: {baselines['seasonal_period']}")
        for name in ("baseline_ultimo_valor", "baseline_media_movel", "baseline_sazonal"):
            b = baselines[name]
            lines.append(
                f"- {name}: wape={b['wape']*100:.2f}% | mae={_fmt_ptbr(b['mae'])} | smape={b['smape']*100:.2f}%"
            )

        lines.append("")
        lines.append("HOLDOUT 80/20 (Prophet - MELHOR):")
        lines.append(f"- wape: {best['wape']*100:.2f}%")
        lines.append(f"- mae: {_fmt_ptbr(best['mae'])}")
        lines.append(f"- smape: {best['smape']*100:.2f}%")
        lines.append(f"- best_params: {best['params']}")

        lines.append("")
        lines.append("CONFIANÇA DO MODELO:")
        lines.append(f"- nível: {confidence['level']}")
        lines.append(f"- resumo: {confidence['summary']}")

        lines.append("")
        lines.append("PREVISÃO (futuro):")
        for r in forecast:
            d = pd.to_datetime(r["ds"]).date().isoformat()
            lines.append(f"- {d}: yhat={_fmt_ptbr(r['yhat'])} | lo={_fmt_ptbr(r['lo'])} | hi={_fmt_ptbr(r['hi'])}")

        lines.append("")
        lines.append("GRAFICO (S3):")
        lines.append(graph_s3_url)
        lines.append("")
        lines.append("GRAFICO (HTTP):")
        lines.append(graph_http_url)

        lines.append("")
        lines.append("ARQUIVO EXCEL (S3):")
        lines.append(excel_s3_url)
        lines.append("")
        lines.append("ARQUIVO EXCEL (HTTP):")
        lines.append(excel_http_url)


        lines.append("")
        lines.append("=" * 70)
        lines.append("FIM")
        return "\n".join(lines)

    # -------------------------------------------------------------------------
    # Tool
    # -------------------------------------------------------------------------

    def _run_previsao_payload(self) -> Callable[[Union[str, Dict[str, Any]]], str]:
        """
        Retorna uma função tool:
        - Entrada: dict ou JSON string
        - Saída: JSON string
        """
        def _tool(input_payload: Union[str, Dict[str, Any]]) -> str:
            # 0) parse
            if input_payload is None:
                return json.dumps([{"_meta": {"ok": False, "error": "Nenhuma entrada foi fornecida (esperado JSON)."}}],
                                  ensure_ascii=False, indent=2)

            if isinstance(input_payload, str):
                if not input_payload.strip():
                    return json.dumps([{"_meta": {"ok": False, "error": "Entrada vazia (esperado JSON)."}}],
                                      ensure_ascii=False, indent=2)
                try:
                    payload = json.loads(input_payload)
                except Exception as e:
                    return json.dumps([{"_meta": {"ok": False, "error": f"Entrada não é JSON válido: {e}"}}],
                                      ensure_ascii=False, indent=2)
            elif isinstance(input_payload, dict):
                payload = input_payload
            else:
                return json.dumps([{"_meta": {"ok": False, "error": "Entrada deve ser JSON string ou dict."}}],
                                  ensure_ascii=False, indent=2)

            # 1) params simples
            date_col = str(payload.get("date_col") or "ds").strip()
            value_col = str(payload.get("value_col") or "y").strip()
            granularity = str(payload.get("granularity") or "monthly").strip()
            horizon = int(payload.get("horizon") or 12)
            label = str(payload.get("label") or "Série (Histórico e Previsão)").strip()

            # 2) dados (Athena ou direto)
            mode = None
            sql = (payload.get("sql") or "").strip()

            try:
                if sql:
                    mode = "athena_sql"
                    rows = self._execute_athena_query(sql)
                else:
                    mode = "direct_data"
                    rows = self._rows_from_payload_data(payload, date_col, value_col)
            except Exception as e:
                return json.dumps([{"_meta": {"ok": False, "stage": "input_or_athena", "mode": mode, "error": str(e)}}],
                                  ensure_ascii=False, indent=2)

            if not rows:
                return json.dumps([{"_meta": {"ok": False, "stage": "data", "mode": mode, "error": "0 linhas/pontos para prever."}}],
                                  ensure_ascii=False, indent=2)

            # 3) série
            try:
                series, series_meta = self._build_series(rows, date_col, value_col, granularity)
            except Exception as e:
                return json.dumps([{"_meta": {"ok": False, "stage": "build_series", "mode": mode, "error": str(e)}}],
                                  ensure_ascii=False, indent=2)

            ds = pd.to_datetime(series.index)
            y = series.values.astype(float)

            # 4) baselines
            freq = _granularity_to_freq(granularity)
            seasonal_period = self._infer_seasonal_period(freq)
            baselines = self._run_baselines_holdout(y, seasonal_period)

            best_baseline_wape = float(min(
                baselines["baseline_ultimo_valor"]["wape"],
                baselines["baseline_media_movel"]["wape"],
                baselines["baseline_sazonal"]["wape"],
            ))

            # 5) Prophet (normal vs robusto) -> melhor
            try:
                h_norm = self._prophet_grid_holdout(ds, y, granularity, use_winsor_train=False)
                h_rob = self._prophet_grid_holdout(ds, y, granularity, use_winsor_train=True)

                if not h_norm.get("ok") and not h_rob.get("ok"):
                    raise RuntimeError(
                        "Prophet não conseguiu rodar. "
                        f"norm_motivo={h_norm.get('motivo')} rob_motivo={h_rob.get('motivo')} "
                        f"norm_errors={h_norm.get('errors_count')} rob_errors={h_rob.get('errors_count')}. "
                        f"sample_norm={h_norm.get('errors_sample')} sample_rob={h_rob.get('errors_sample')}"
                    )

                candidates: List[Tuple[Dict[str, Any], bool]] = []
                if h_norm.get("ok") and h_norm.get("best"):
                    candidates.append((h_norm["best"], False))
                if h_rob.get("ok") and h_rob.get("best"):
                    candidates.append((h_rob["best"], True))

                candidates.sort(key=lambda t: float(t[0]["wape"]))
                best, best_use_winsor = candidates[0]
            except Exception as e:
                return json.dumps([{"_meta": {"ok": False, "stage": "prophet_holdout", "mode": mode, "error": str(e)}}],
                                  ensure_ascii=False, indent=2)

            # 6) forecast
            try:
                forecast = self._prophet_fit_and_forecast(
                    ds=ds,
                    y=y,
                    granularity=granularity,
                    horizon=horizon,
                    best_params=best["params"],
                    use_winsor_full_train=best_use_winsor,
                )
            except Exception as e:
                return json.dumps([{"_meta": {"ok": False, "stage": "prophet_forecast", "mode": mode, "error": str(e)}}],
                                  ensure_ascii=False, indent=2)

            # 7) gráfico + S3 + HTTP
            try:
                graph_s3_url, graph_http_url = self._upload_graph_s3_and_presign(series, forecast, label)
            except Exception as e:
                return json.dumps([{"_meta": {"ok": False, "stage": "graph_s3", "mode": mode, "error": str(e)}}],
                                  ensure_ascii=False, indent=2)
            
            # 7.1) excel + S3 + HTTP
            try:
                export_df = self._build_export_dataframe(series, forecast)
                excel_local_path = self._write_excel(df=export_df, label=label)
                excel_s3_url, excel_http_url = self._upload_excel_s3_and_presign(excel_local_path)
            except Exception as e:
                return json.dumps([{"_meta": {"ok": False, "stage": "excel_s3", "mode": mode, "error": str(e)}}],
                                ensure_ascii=False, indent=2)


            # 8) confiança
            level, summary = _classificar_confianca(
                wape_val=float(best["wape"]),
                smape_val=float(best["smape"]),
                wape_baseline_ref=best_baseline_wape,
            )
            confidence = {"level": level, "summary": summary}

            # 9) TXT
            report_txt = self._build_report_txt(
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


            # 10) JSON (meta + history + forecast)
            hist_df = pd.DataFrame({"ds": series.index, "y": series.values})
            hist_df["type"] = "history"
            hist_df["yhat"] = None
            hist_df["lo"] = None
            hist_df["hi"] = None

            fc_df = pd.DataFrame([{
                "ds": r["ds"],
                "y": None,
                "yhat": r["yhat"],
                "lo": r["lo"],
                "hi": r["hi"],
                "type": "forecast"
            } for r in forecast])

            all_df = pd.concat([hist_df, fc_df], ignore_index=True)
            all_df["ds"] = pd.to_datetime(all_df["ds"], errors="coerce").dt.strftime("%Y-%m-%d")

            meta = {
                "ok": True,
                "mode": mode,
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
                "report_txt": report_txt,
            }


            out_list: List[Dict[str, Any]] = [{"_meta": meta}]
            out_list.extend(all_df.to_dict(orient="records"))

            return json.dumps(out_list, ensure_ascii=False, indent=2)

        return _tool
    
    def run_previsao_tool(self) -> Callable[..., str]:
        """
        Tool com assinatura explícita (para o agente chamar tipo função):
        run_previsao(sql="...", granularity="monthly", horizon=12, label="...")

        Internamente, monta o payload e chama a tool original (run_previsao()).
        """
        base_tool = self._run_previsao_payload()  # <- essa é a tool atual que recebe payload

        def _tool(
            sql: str,
            granularity: str = "monthly",
            horizon: int = 12,
            label: str = "Série (Histórico e Previsão)",
            date_col: str = "ds",
            value_col: str = "y",
        ) -> str:
            # Guardrails básicos
            if not isinstance(sql, str) or not sql.strip():
                return json.dumps([{"_meta": {"ok": False, "error": "SQL vazia ou inválida."}}],
                                ensure_ascii=False, indent=2)

            payload = {
                "sql": sql.strip(),
                "granularity": (granularity or "monthly").strip(),
                "horizon": int(horizon),
                "label": (label or "Série (Histórico e Previsão)").strip(),
                "date_col": (date_col or "ds").strip(),
                "value_col": (value_col or "y").strip(),
            }

            # Chama a tool original passando dict (ela aceita dict ou string JSON)
            return base_tool(payload)

        return _tool
