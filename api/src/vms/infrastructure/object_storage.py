"""Cliente MinIO genérico (staging S3-compatível) para o Next Sec.

Substitui `vms.recordings.storage.RecordingStorage` (não copiado do vms/ —
gravação contínua fora de escopo, ver .genesis/architecture/reuse-plan.md).
Ao contrário do original, este cliente não assume nenhum conceito de
"gravação" — apenas operações genéricas de objeto sobre um bucket informado
pelo chamador (snapshots de evento, clipes em staging antes do upload ao
StorageProvider final — ver ADR-010).
"""

from __future__ import annotations

import logging
from typing import Any

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError

from vms.infrastructure.config import get_settings

logger = logging.getLogger(__name__)


class ObjectStorage:
    """Abstração fina sobre boto3 apontando para o MinIO do docker-compose."""

    def __init__(self) -> None:
        settings = get_settings()
        endpoint_url = settings.minio_endpoint
        if endpoint_url and not endpoint_url.startswith("http"):
            endpoint_url = f"http://{endpoint_url}"

        self._client = boto3.client(
            "s3",
            aws_access_key_id=settings.minio_access_key,
            aws_secret_access_key=settings.minio_secret_key,
            config=Config(signature_version="s3v4"),
            region_name="us-east-1",
            endpoint_url=endpoint_url or None,
        )

    def ensure_bucket(self, bucket: str) -> None:
        """Cria o bucket se ele ainda não existir."""
        try:
            self._client.head_bucket(Bucket=bucket)
        except ClientError:
            self._client.create_bucket(Bucket=bucket)

    def upload_bytes(self, bucket: str, key: str, data: bytes, content_type: str = "application/octet-stream") -> None:
        self.ensure_bucket(bucket)
        self._client.put_object(Bucket=bucket, Key=key, Body=data, ContentType=content_type)

    def delete_object(self, bucket: str, key: str) -> None:
        self._client.delete_object(Bucket=bucket, Key=key)

    def get_presigned_url(self, bucket: str, key: str, expires: int = 3600) -> str:
        return self._client.generate_presigned_url(
            "get_object",
            Params={"Bucket": bucket, "Key": key},
            ExpiresIn=expires,
        )
