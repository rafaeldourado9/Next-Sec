"""Storage Provider — destino final do clipe/frame do evento (ADR-010, revisado).

Interface isolada do provider concreto: hoje só existe `MinIOStorageProvider`
(storage local na própria VPS, sem credencial externa — decisão do usuário no
Sprint 4). Um provider externo (Google Drive, S3...) pode ser adicionado depois
como uma segunda implementação desta mesma interface, sem tocar em quem a usa.
"""
from __future__ import annotations

from typing import Protocol

from vms.infrastructure.config import get_settings
from vms.infrastructure.object_storage import ObjectStorage


class StorageProvider(Protocol):
    """Destino final onde o clipe/frame de um evento é armazenado."""

    async def upload(self, local_path: str, key: str, content_type: str) -> str:
        """Envia o arquivo e retorna a URL de acesso (pode ser pré-assinada)."""
        ...

    async def delete(self, key: str) -> None:
        """Remove o objeto do storage."""
        ...


class MinIOStorageProvider:
    """Storage local — usa o MinIO que já roda na mesma VPS (ver ADR-010)."""

    def __init__(self, storage: ObjectStorage | None = None) -> None:
        self._storage = storage or ObjectStorage()
        self._bucket = get_settings().minio_bucket_clips

    async def upload(self, local_path: str, key: str, content_type: str = "video/mp4") -> str:
        with open(local_path, "rb") as f:
            data = f.read()
        self._storage.upload_bytes(self._bucket, key, data, content_type=content_type)
        # 7 dias — tempo suficiente para o cliente final abrir o link da notificação
        # sem expor o objeto como público permanente.
        return self._storage.get_presigned_url(self._bucket, key, expires=7 * 24 * 3600)

    async def delete(self, key: str) -> None:
        self._storage.delete_object(self._bucket, key)


def build_storage_provider() -> StorageProvider:
    """Factory — seleciona o provider ativo via STORAGE_PROVIDER (env var)."""
    provider = get_settings().storage_provider
    if provider == "local":
        return MinIOStorageProvider()
    raise ValueError(
        f"STORAGE_PROVIDER='{provider}' desconhecido — implementações disponíveis: 'local'"
    )
