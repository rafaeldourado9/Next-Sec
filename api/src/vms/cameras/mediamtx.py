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

    async def add_path(
        self,
        path: str,
        source_url: str = "",
        recording_enabled: bool = False,
        retention_days: int | None = None,
        force: bool = False,
    ) -> bool:
        """
        Upsert de path de stream no MediaMTX. Retorna True se OK.

        - source_url vazio: aceita qualquer publisher (RTMP push)
        - source_url preenchido: pull RTSP (modo agent)
        - recording_enabled: liga gravação contínua nesse path específico
          (ver incidente documentado abaixo — default é False)
        - force: ignora o early-return e reafirma a config mesmo se o path já
          está ativo em runtime. Só o chamador (CameraService.update_camera)
          sabe quando um campo relevante (recording_enabled/retention_days)
          de fato mudou — sem isso, main.py/watchdog reprovisionando TODAS as
          câmeras no boot faria edit+add em cada uma toda vez, sem necessidade
          e com risco de mexer num path RTSP já ao vivo à toa.

        Estratégia:
        1. Verifica runtime: se path já está ativo e não é force, retorna
           True sem ruído (early-return original — preserva o path ao vivo).
        2. Tenta edit (config existente): atualiza se já provisionado antes.
        3. Tenta add (config nova): cria fresh.
        """
        # NOTA (Next Sec): incidente anterior — `record: True` global (via
        # mediamtx.yml pathDefaults) derrubava o muxer HLS ao vivo junto,
        # porque o recorder travava em frames fora de ordem (câmera real via
        # WiFi/RTSP instável). A correção na época foi reverter a gravação
        # inteira. Reintroduzida agora como opt-in por câmera
        # (recording_enabled, default False) + sourceProtocol tcp forçado
        # (abaixo) + recordSegmentDuration curto (mediamtx.yml) pra limitar o
        # raio de explosão de um segmento corrompido. Rollout em canário
        # obrigatório antes de ligar em mais de uma câmera — ver plano.
        body: dict = {}
        if source_url:
            body["source"] = source_url
            # RTSP fonte real (câmera física) — força TCP. UDP perde/reordena
            # pacote com frequência em rede doméstica, o que quebrava o muxer
            # HLS (ver "too many reordered frames" nos logs do mediamtx).
            body["sourceProtocol"] = "tcp"
        if recording_enabled:
            body["record"] = True
            body["recordDeleteAfter"] = f"{(retention_days or 7) * 86400}s"
        else:
            # Explícito — sem isso, desligar recording_enabled numa câmera já
            # provisionada com gravação ligada não tinha efeito nenhum (o
            # runtime-check abaixo faria early-return antes de chegar no edit).
            body["record"] = False

        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                # 1. Path já está ativo como stream runtime? Nada a fazer,
                # a menos que force=True (ver docstring).
                runtime_resp = await client.get(
                    f"{self._base_url}/v3/paths/get/{path}"
                )
                if runtime_resp.status_code == 200 and not force:
                    logger.debug("Path MediaMTX já ativo (runtime): %s", path)
                    return True

                # 2. Tenta criar config nova.
                add_resp = await client.post(
                    f"{self._base_url}/v3/config/paths/add/{path}", json=body
                )
                if add_resp.status_code == 200:
                    logger.debug("Path MediaMTX criado: %s", path)
                    return True

                # 3. Config já existe (400) — reconfigura via delete+add.
                # NOTA (Next Sec): `config/paths/edit/{name}` retorna 404 de
                # ROTA (não erro de app — "404 page not found" cru do Go
                # router) pra nomes de path com "/" — que é exatamente o
                # nosso esquema (tenant-{id}/cam-{id}). Confirmado via teste
                # direto durante o canário de gravação: edit nunca funcionava,
                # e o código antigo tratava o 400 subsequente do add como
                # "já existe, sucesso" — mascarando que a config NUNCA era de
                # fato atualizada (recording_enabled ficava sempre False no
                # MediaMTX, mesmo com force=True). delete+add é o único
                # caminho que realmente reconfigura um path existente nesta
                # versão — custa uma breve reconexão do stream, aceitável
                # numa mudança de config deliberada (não roda em loop).
                if add_resp.status_code == 400:
                    await client.delete(f"{self._base_url}/v3/config/paths/delete/{path}")
                    retry_resp = await client.post(
                        f"{self._base_url}/v3/config/paths/add/{path}", json=body
                    )
                    if retry_resp.status_code == 200:
                        logger.debug("Path MediaMTX reconfigurado (delete+add): %s", path)
                        return True
                    logger.warning(
                        "Erro ao reconfigurar path '%s' via delete+add: %s — %s",
                        path, retry_resp.status_code, retry_resp.text,
                    )
                    return False

                logger.warning(
                    "Erro ao criar path '%s': %s — %s",
                    path, add_resp.status_code, add_resp.text,
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
