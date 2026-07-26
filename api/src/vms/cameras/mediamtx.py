"""Cliente HTTP para a API v3 do MediaMTX."""
from __future__ import annotations

import logging

import httpx

from vms.infrastructure.config import get_settings

logger = logging.getLogger(__name__)


class MediaMTXClient:
    """Cliente assíncrono para gerenciar paths no MediaMTX."""

    def __init__(self, base_url: str | None = None) -> None:
        self._base_url = base_url or get_settings().mediamtx_api_url

    async def health_check(self) -> bool:
        """
        Verifica se a API do MediaMTX está respondendo.
        Retorna True se saudável, False caso contrário.
        """
        # Tenta acessar a API de controle do MediaMTX
        url = f"{self._base_url}/v3/config/global/get"
        try:
            async with httpx.AsyncClient(timeout=5.0, follow_redirects=True) as client:
                response = await client.get(url)
                if response.status_code == 200:
                    logger.info("Health check MediaMTX OK via %s", self._base_url)
                    return True
                else:
                    logger.warning("Health check MediaMTX status: %d via %s", response.status_code, self._base_url)
                    return False
        except httpx.ConnectError as exc:
            logger.warning("Health check MediaMTX falhou (connect): %s - %s", self._base_url, exc)
            return False
        except Exception as exc:
            logger.warning("Health check MediaMTX falhou (%s): %s - %s", type(exc).__name__, self._base_url, exc)
            return False

    async def add_path(self, path: str, source_url: str = "") -> bool:
        """
        Upsert de path de stream no MediaMTX. Retorna True se OK.

        - source_url vazio: aceita qualquer publisher (RTMP push)
        - source_url preenchido: pull RTSP (modo agent)

        Estratégia:
        1. Verifica runtime: se path já está ativo, retorna True sem ruído.
        2. Tenta edit (config existente): atualiza se já provisionado antes.
        3. Tenta add (config nova): cria fresh.
        """
        body: dict = {
            "record": True,
            "recordPath": "/recordings/%path/%Y/%m/%d/%H-%M-%S-%f",
        }
        if source_url:
            body["source"] = source_url

        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                # 1. Path já está ativo como stream runtime? Nada a fazer.
                runtime_resp = await client.get(
                    f"{self._base_url}/v3/paths/get/{path}"
                )
                if runtime_resp.status_code == 200:
                    logger.debug("Path MediaMTX já ativo (runtime): %s", path)
                    return True

                # 2. Tenta atualizar config existente
                edit_resp = await client.post(
                    f"{self._base_url}/v3/config/paths/edit/{path}", json=body
                )
                if edit_resp.status_code == 200:
                    logger.debug("Path MediaMTX config atualizado: %s", path)
                    return True

                # 3. Config não existe — cria
                if edit_resp.status_code == 404:
                    add_resp = await client.post(
                        f"{self._base_url}/v3/config/paths/add/{path}", json=body
                    )
                    if add_resp.status_code in (200, 400):
                        logger.debug("Path MediaMTX criado: %s", path)
                        return True
                    logger.warning(
                        "Erro ao criar path '%s': %s — %s",
                        path, add_resp.status_code, add_resp.text,
                    )
                    return False

                logger.warning(
                    "Erro ao atualizar path '%s': %s — %s",
                    path, edit_resp.status_code, edit_resp.text,
                )
                return False
        except Exception as exc:
            logger.warning("Falha ao provisionar path '%s' no MediaMTX: %s", path, exc)
            return False
    
    async def add_playback_path(self, path_name: str, file_path: str) -> bool:
        """
        Cria path temporário no MediaMTX apontando para um arquivo MP4 local.

        MediaMTX lê o arquivo e serve como stream HLS (remux sem reencoding).
        O path se auto-remove após ficar ocioso por 1h (sourceOnDemandCloseAfter).
        """
        url = f"{self._base_url}/v3/config/paths/add/{path_name}"
        body: dict = {
            "source": f"file://{file_path}",
            "record": False,
            "sourceOnDemand": True,
            "sourceOnDemandCloseAfter": "3600s",
        }
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.post(url, json=body)
                if response.status_code == 200:
                    logger.debug("Playback path criado: %s → %s", path_name, file_path)
                    return True
                if response.status_code == 400:
                    # Já existe — idempotente
                    logger.debug("Playback path já existe: %s", path_name)
                    return True
                logger.warning(
                    "Erro ao criar playback path '%s': %s — %s",
                    path_name,
                    response.status_code,
                    response.text,
                )
                return False
        except Exception as exc:
            logger.warning("Falha ao criar playback path '%s': %s", path_name, exc)
            return False

    async def remove_path(self, path: str) -> bool:
        """Remove path de stream. Retorna True se OK."""
        url = f"{self._base_url}/v3/config/paths/delete/{path}"
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.delete(url)
                response.raise_for_status()
                logger.debug("Path MediaMTX removido: %s", path)
                return True
        except httpx.HTTPStatusError as exc:
            logger.warning(
                "Erro HTTP ao remover path '%s' do MediaMTX: %s",
                path,
                exc.response.status_code,
            )
            return False
        except Exception as exc:
            logger.warning("Falha ao remover path '%s' do MediaMTX: %s", path, exc)
            return False

    async def list_paths(self) -> list[dict]:
        """Lista todos os paths ativos."""
        url = f"{self._base_url}/v3/paths/list"
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(url)
                response.raise_for_status()
                data = response.json()
                return data.get("items", [])
        except Exception as exc:
            logger.warning("Falha ao listar paths do MediaMTX: %s", exc)
            return []
