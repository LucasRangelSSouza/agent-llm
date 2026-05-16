from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, Iterable, Optional, Tuple

import httpx
import pandas as pd

from ui.backend.core.db import get_connection
from ui.backend.services.file_storage import save_file_bytes


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _slugify(value: str, fallback: str) -> str:
    import re

    text = re.sub(r"[^A-Za-z0-9._-]+", "_", str(value or "").strip()).strip("._")
    return text or fallback


def _artifact_base_prefix(
    *,
    tenant_id: Optional[str],
    kind: str,
    module_name: Optional[str],
    agent_name: Optional[str],
    artifact_id: str,
) -> str:
    return (
        f"tenants/{tenant_id or 'unknown'}/artifacts/{kind}/"
        f"{_slugify(module_name or 'module', 'module')}/"
        f"{_slugify(agent_name or 'agent', 'agent')}/{artifact_id}"
    )


def _build_schema_from_df(df: pd.DataFrame) -> list[dict]:
    return [{"name": str(column), "type": str(dtype)} for column, dtype in df.dtypes.items()]


def _preview_rows(df: pd.DataFrame, limit: int = 50) -> list[dict]:
    if df.empty:
        return []
    preview_df = df.head(max(1, int(limit or 50))).copy()
    preview_df = preview_df.where(pd.notnull(preview_df), None)
    return preview_df.to_dict(orient="records")


def _dataframe_from_rows(rows: Iterable[dict]) -> pd.DataFrame:
    df = pd.DataFrame(list(rows or []))
    return df.where(pd.notnull(df), None)


def save_dataset_artifact(
    *,
    tenant_id: Optional[str],
    user_id: Optional[str],
    chat_id: Optional[str],
    module_name: Optional[str],
    agent_name: Optional[str],
    label: str,
    dataframe: pd.DataFrame,
    source_tool: str,
    source_type: str,
    metadata: Optional[dict] = None,
) -> dict:
    artifact_id = uuid.uuid4().hex
    label = label or "dataset"
    df = dataframe.copy().where(pd.notnull(dataframe), None)
    base_prefix = _artifact_base_prefix(
        tenant_id=tenant_id,
        kind="dataset",
        module_name=module_name,
        agent_name=agent_name,
        artifact_id=artifact_id,
    )

    parquet_buffer = BytesIO()
    df.to_parquet(parquet_buffer, index=False)
    parquet_bytes = parquet_buffer.getvalue()
    parquet_file = save_file_bytes(
        tenant_id=tenant_id,
        user_id=user_id,
        chat_id=chat_id,
        filename=f"{_slugify(label, 'dataset')}.parquet",
        content=parquet_bytes,
        content_type="application/octet-stream",
        kind="artifact_dataset_data",
        metadata={"artifact_id": artifact_id, "artifact_kind": "dataset", "role": "data"},
        path_prefix=f"{base_prefix}/data",
    )

    preview = {
        "columns": [str(column) for column in df.columns],
        "rows": _preview_rows(df),
    }
    preview_bytes = json.dumps(preview, ensure_ascii=False, default=str).encode("utf-8")
    preview_file = save_file_bytes(
        tenant_id=tenant_id,
        user_id=user_id,
        chat_id=chat_id,
        filename=f"{_slugify(label, 'dataset')}_preview.json",
        content=preview_bytes,
        content_type="application/json",
        kind="artifact_dataset_preview",
        metadata={"artifact_id": artifact_id, "artifact_kind": "dataset", "role": "preview"},
        path_prefix=f"{base_prefix}/preview",
    )

    manifest = {
        "artifact_version": 1,
        "artifact_id": artifact_id,
        "artifact_kind": "dataset",
        "label": label,
        "created_at": _utcnow_iso(),
        "module_name": module_name,
        "agent_name": agent_name,
        "tenant_id": tenant_id,
        "source_tool": source_tool,
        "source_type": source_type,
        "schema": _build_schema_from_df(df),
        "row_count": int(df.shape[0]),
        "column_count": int(df.shape[1]),
        "storage": {
            "primary_format": "parquet",
            "data_url": parquet_file.get("public_url"),
            "preview_url": preview_file.get("public_url"),
        },
        "preview": preview,
        "metadata": metadata or {},
    }
    manifest_bytes = json.dumps(manifest, ensure_ascii=False, default=str, indent=2).encode("utf-8")
    manifest_file = save_file_bytes(
        tenant_id=tenant_id,
        user_id=user_id,
        chat_id=chat_id,
        filename=f"{_slugify(label, 'dataset')}_artifact.json",
        content=manifest_bytes,
        content_type="application/json",
        kind="artifact_manifest",
        metadata={"artifact_id": artifact_id, "artifact_kind": "dataset", "role": "manifest"},
        path_prefix=f"{base_prefix}/manifest",
    )
    manifest["storage"]["manifest_url"] = manifest_file.get("public_url")
    manifest["storage"]["manifest_file_id"] = manifest_file.get("id")
    return manifest


def save_document_artifact(
    *,
    tenant_id: Optional[str],
    user_id: Optional[str],
    chat_id: Optional[str],
    module_name: Optional[str],
    agent_name: Optional[str],
    label: str,
    content: dict,
    source_tool: str,
    source_type: str,
    metadata: Optional[dict] = None,
) -> dict:
    artifact_id = uuid.uuid4().hex
    label = label or "document"
    base_prefix = _artifact_base_prefix(
        tenant_id=tenant_id,
        kind="document",
        module_name=module_name,
        agent_name=agent_name,
        artifact_id=artifact_id,
    )

    content_bytes = json.dumps(content, ensure_ascii=False, default=str, indent=2).encode("utf-8")
    content_file = save_file_bytes(
        tenant_id=tenant_id,
        user_id=user_id,
        chat_id=chat_id,
        filename=f"{_slugify(label, 'document')}.json",
        content=content_bytes,
        content_type="application/json",
        kind="artifact_document_data",
        metadata={"artifact_id": artifact_id, "artifact_kind": "document", "role": "data"},
        path_prefix=f"{base_prefix}/data",
    )

    manifest = {
        "artifact_version": 1,
        "artifact_id": artifact_id,
        "artifact_kind": "document",
        "label": label,
        "created_at": _utcnow_iso(),
        "module_name": module_name,
        "agent_name": agent_name,
        "tenant_id": tenant_id,
        "source_tool": source_tool,
        "source_type": source_type,
        "document_summary": content.get("document_summary") or content.get("answer") or "",
        "chunk_count": len(content.get("chunks") or []),
        "storage": {
            "primary_format": "json",
            "data_url": content_file.get("public_url"),
        },
        "preview": {
            "files": content.get("files") or [],
            "answer": content.get("answer") or "",
            "chunks": (content.get("chunks") or [])[:5],
        },
        "metadata": metadata or {},
    }
    manifest_bytes = json.dumps(manifest, ensure_ascii=False, default=str, indent=2).encode("utf-8")
    manifest_file = save_file_bytes(
        tenant_id=tenant_id,
        user_id=user_id,
        chat_id=chat_id,
        filename=f"{_slugify(label, 'document')}_artifact.json",
        content=manifest_bytes,
        content_type="application/json",
        kind="artifact_manifest",
        metadata={"artifact_id": artifact_id, "artifact_kind": "document", "role": "manifest"},
        path_prefix=f"{base_prefix}/manifest",
    )
    manifest["storage"]["manifest_url"] = manifest_file.get("public_url")
    manifest["storage"]["manifest_file_id"] = manifest_file.get("id")
    return manifest


def resolve_artifact_url(*, artifact_url: Optional[str] = None, artifact_id: Optional[str] = None) -> str:
    if artifact_url:
        return artifact_url
    if artifact_id:
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT public_url
                FROM agent_files
                WHERE id = %s
                   OR metadata_json ->> 'artifact_id' = %s
                LIMIT 1
                """,
                (artifact_id, artifact_id),
            )
            row = cur.fetchone()
        if row and row.get("public_url"):
            return row["public_url"]
    raise ValueError("Informe artifact_url ou artifact_id.")


def load_artifact_manifest(*, artifact_url: Optional[str] = None, artifact_id: Optional[str] = None) -> dict:
    url = resolve_artifact_url(artifact_url=artifact_url, artifact_id=artifact_id)
    with httpx.Client(timeout=60.0, follow_redirects=True) as client:
        response = client.get(url)
        response.raise_for_status()
        return response.json()


def load_dataset_artifact(*, artifact_url: Optional[str] = None, artifact_id: Optional[str] = None) -> Tuple[dict, pd.DataFrame]:
    manifest = load_artifact_manifest(artifact_url=artifact_url, artifact_id=artifact_id)
    if manifest.get("artifact_kind") != "dataset":
        raise ValueError(f"Artifact informado nao eh dataset: {manifest.get('artifact_kind')}")
    data_url = ((manifest.get("storage") or {}).get("data_url")) or ""
    if not data_url:
        raise ValueError("Dataset artifact sem data_url.")
    with httpx.Client(timeout=120.0, follow_redirects=True) as client:
        response = client.get(data_url)
        response.raise_for_status()
        data = BytesIO(response.content)
    return manifest, pd.read_parquet(data)


def load_document_artifact(*, artifact_url: Optional[str] = None, artifact_id: Optional[str] = None) -> Tuple[dict, dict]:
    manifest = load_artifact_manifest(artifact_url=artifact_url, artifact_id=artifact_id)
    if manifest.get("artifact_kind") != "document":
        raise ValueError(f"Artifact informado nao eh document: {manifest.get('artifact_kind')}")
    data_url = ((manifest.get("storage") or {}).get("data_url")) or ""
    if not data_url:
        raise ValueError("Document artifact sem data_url.")
    with httpx.Client(timeout=120.0, follow_redirects=True) as client:
        response = client.get(data_url)
        response.raise_for_status()
        return manifest, response.json()


def artifact_summary_text(manifest: dict) -> str:
    if manifest.get("artifact_kind") == "dataset":
        preview = manifest.get("preview") or {}
        return json.dumps(
            {
                "artifact_id": manifest.get("artifact_id"),
                "artifact_kind": manifest.get("artifact_kind"),
                "label": manifest.get("label"),
                "row_count": manifest.get("row_count"),
                "schema": manifest.get("schema"),
                "manifest_url": ((manifest.get("storage") or {}).get("manifest_url")),
                "data_url": ((manifest.get("storage") or {}).get("data_url")),
                "preview": preview,
            },
            ensure_ascii=False,
        )
    return json.dumps(
        {
            "artifact_id": manifest.get("artifact_id"),
            "artifact_kind": manifest.get("artifact_kind"),
            "label": manifest.get("label"),
            "chunk_count": manifest.get("chunk_count"),
            "manifest_url": ((manifest.get("storage") or {}).get("manifest_url")),
            "data_url": ((manifest.get("storage") or {}).get("data_url")),
            "preview": manifest.get("preview") or {},
        },
        ensure_ascii=False,
    )
