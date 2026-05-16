import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import PurePosixPath
from urllib.parse import quote

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError
from psycopg2.extras import Json

from ui.backend.core import config
from ui.backend.core.db import get_connection, new_id


_bucket_ready = False


def _s3_client():
    return boto3.client(
        "s3",
        endpoint_url=config.FILE_STORAGE_ENDPOINT,
        aws_access_key_id=config.FILE_STORAGE_ACCESS_KEY,
        aws_secret_access_key=config.FILE_STORAGE_SECRET_KEY,
        region_name=config.FILE_STORAGE_REGION,
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
    )


def _safe_filename(filename: str) -> str:
    name = PurePosixPath(filename or "arquivo").name
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("._")
    return name or "arquivo"


def _public_object_url(bucket: str, object_key: str) -> str:
    quoted_key = "/".join(quote(part) for part in object_key.split("/"))
    return f"{config.FILE_STORAGE_PUBLIC_ENDPOINT}/{bucket}/{quoted_key}"


def _ensure_bucket() -> None:
    global _bucket_ready
    if _bucket_ready:
        return

    client = _s3_client()
    bucket = config.FILE_STORAGE_BUCKET
    try:
        client.head_bucket(Bucket=bucket)
    except ClientError:
        client.create_bucket(Bucket=bucket)

    if config.FILE_STORAGE_URL_MODE == "permanent":
        policy = {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Effect": "Allow",
                    "Principal": "*",
                    "Action": ["s3:GetObject"],
                    "Resource": [f"arn:aws:s3:::{bucket}/*"],
                }
            ],
        }
        client.put_bucket_policy(Bucket=bucket, Policy=json.dumps(policy))

    _bucket_ready = True


def build_download_url(bucket: str, object_key: str) -> tuple[str, datetime | None, bool]:
    if config.FILE_STORAGE_URL_MODE == "signed":
        expires_in = max(config.FILE_STORAGE_SIGNED_URL_EXPIRES_SECONDS, 1)
        url = _s3_client().generate_presigned_url(
            "get_object",
            Params={"Bucket": bucket, "Key": object_key},
            ExpiresIn=expires_in,
        )
        url = url.replace(config.FILE_STORAGE_ENDPOINT, config.FILE_STORAGE_PUBLIC_ENDPOINT, 1)
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)
        return url, expires_at, False

    return _public_object_url(bucket, object_key), None, True


def save_file_bytes(
    *,
    tenant_id: str | None,
    user_id: str | None,
    chat_id: str | None,
    filename: str,
    content: bytes,
    content_type: str | None,
    kind: str = "chat_upload",
    datasource_id: str | None = None,
    template_id: str | None = None,
    metadata: dict | None = None,
    path_prefix: str | None = None,
) -> dict:
    _ensure_bucket()

    file_id = new_id()
    safe_name = _safe_filename(filename)
    now = datetime.now(timezone.utc)
    base_prefix = path_prefix or f"tenants/{tenant_id or 'unknown'}/chats/{chat_id or 'no-chat'}/uploads"
    object_key = f"{base_prefix}/{now:%Y/%m/%d}/{file_id}_{safe_name}"
    bucket = config.FILE_STORAGE_BUCKET
    checksum = hashlib.sha256(content).hexdigest()

    _s3_client().put_object(
        Bucket=bucket,
        Key=object_key,
        Body=content,
        ContentType=content_type or "application/octet-stream",
        Metadata={
            "file-id": file_id,
            "tenant-id": tenant_id or "",
            "chat-id": chat_id or "",
            "original-filename": safe_name,
        },
    )

    public_url, expires_at, is_public = build_download_url(bucket, object_key)
    row = {
        "id": file_id,
        "tenant_id": tenant_id,
        "user_id": user_id,
        "chat_id": chat_id,
        "datasource_id": datasource_id,
        "template_id": template_id,
        "kind": kind,
        "original_filename": filename or safe_name,
        "storage_provider": "s3",
        "bucket": bucket,
        "object_key": object_key,
        "public_url": public_url,
        "content_type": content_type or "application/octet-stream",
        "size_bytes": len(content),
        "checksum_sha256": checksum,
        "is_public": is_public,
        "expires_at": expires_at,
        "metadata_json": metadata or {},
    }

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO agent_files (
                id,
                tenant_id,
                user_id,
                chat_id,
                datasource_id,
                template_id,
                kind,
                original_filename,
                storage_provider,
                bucket,
                object_key,
                public_url,
                content_type,
                size_bytes,
                checksum_sha256,
                is_public,
                expires_at,
                metadata_json
            )
            VALUES (
                %(id)s,
                %(tenant_id)s,
                %(user_id)s,
                %(chat_id)s,
                %(datasource_id)s,
                %(template_id)s,
                %(kind)s,
                %(original_filename)s,
                %(storage_provider)s,
                %(bucket)s,
                %(object_key)s,
                %(public_url)s,
                %(content_type)s,
                %(size_bytes)s,
                %(checksum_sha256)s,
                %(is_public)s,
                %(expires_at)s,
                %(metadata_json)s
            )
            RETURNING *
            """,
            {**row, "metadata_json": Json(row["metadata_json"])},
        )
        saved = cur.fetchone()

    return dict(saved)
