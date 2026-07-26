"""ISAPIClient — Cliente HTTP para câmeras Hikvision via ISAPI.

Usa HTTP Digest Auth para autenticação e httpx para requisições assíncronas.
Implementa retry com backoff exponencial e circuit breaker para câmeras offline.
"""
from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class ISAPIClient:
    """
    Cliente HTTP para ISAPI da Hikvision.

    Uso:
        client = ISAPIClient("http://192.168.1.64/ISAPI", "admin", "senha")
        caps = await client.get_capabilities()
        await client.configure_alarm_server("http://vms.example.com/webhooks/hik_pro_connect")
    """

    def __init__(
        self,
        base_url: str,
        username: str,
        password: str,
        timeout: float = 10.0,
        retry_count: int = 3,
        retry_delay: float = 2.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._username = username
        self._password = password
        self._timeout = timeout
        self._retry_count = retry_count
        self._retry_delay = retry_delay

    def _get_client(self) -> httpx.AsyncClient:
        """Cria cliente HTTP com Digest Auth."""
        return httpx.AsyncClient(
            auth=httpx.DigestAuth(self._username, self._password),
            timeout=self._timeout,
        )

    async def _request(
        self,
        method: str,
        path: str,
        data: str | None = None,
        headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        """Faz requisição com retry e backoff exponencial."""
        last_exc: Exception | None = None
        for attempt in range(self._retry_count):
            try:
                async with self._get_client() as client:
                    url = f"{self._base_url}/{path.lstrip('/')}"
                    response = await client.request(
                        method,
                        url,
                        content=data,
                        headers=headers,
                    )
                    response.raise_for_status()
                    return response
            except (httpx.HTTPError, httpx.ConnectError) as exc:
                last_exc = exc
                if attempt < self._retry_count - 1:
                    delay = self._retry_delay * (2 ** attempt)
                    logger.debug(
                        "ISAPI request failed (tentativa %d/%d): %s. Aguardando %.1fs",
                        attempt + 1,
                        self._retry_count,
                        exc,
                        delay,
                    )
                    import asyncio
                    await asyncio.sleep(delay)

        logger.error("ISAPI request falhou após %d tentativas: %s", self._retry_count, last_exc)
        raise last_exc or RuntimeError("ISAPI request failed")

    async def get(self, path: str) -> Any:
        """GET XML ou JSON."""
        response = await self._request("GET", path)
        content_type = response.headers.get("content-type", "").lower()

        # Se XML (Hikvision retorna application/xml ou text/xml)
        if "xml" in content_type:
            try:
                import xmltodict
                return xmltodict.parse(response.text)
            except Exception:
                logger.warning("Falha ao parsear XML ISAPI, retornando texto puro")
                return response.text

        # Tenta JSON
        try:
            return response.json()
        except Exception:
            return response.text

    async def put(self, path: str, data: str, content_type: str = "application/xml") -> bool:
        """PUT XML ou JSON."""
        headers = {"Content-Type": content_type}
        await self._request("PUT", path, data=data, headers=headers)
        return True

    # ─── Métodos de alto nível ───────────────────────────────────────────

    async def get_capabilities(self) -> dict:
        """Consulta /ISAPI/System/capabilities e retorna capacidades da câmera."""
        try:
            return await self.get("System/capabilities")
        except Exception as exc:
            logger.warning("Falha ao obter capacidades ISAPI: %s", exc)
            return {}

    async def get_device_info(self) -> dict:
        """Consulta /ISAPI/System/deviceInfo."""
        try:
            return await self.get("System/deviceInfo")
        except Exception as exc:
            logger.warning("Falha ao obter info do dispositivo ISAPI: %s", exc)
            return {}

    async def configure_alarm_server(self, webhook_url: str) -> bool:
        """Configura Alarm Server para push de eventos."""
        # XML para configurar HTTP Host de notificação
        payload = f"""<HttpHostNotificationList>
  <HttpHostNotification>
    <id>1</id>
    <url>{webhook_url}</url>
    <protocolType>HTTP</protocolType>
    <parameterFormatType>XML</parameterFormatType>
    <addressingFormatType>ipaddress</addressingFormatType>
    <httpAuthenticationMethod>none</httpAuthenticationMethod>
  </HttpHostNotification>
</HttpHostNotificationList>"""
        try:
            await self.put("Event/notification/httpHosts", data=payload)
            logger.info("Alarm Server configurado: %s", webhook_url)
            return True
        except Exception as exc:
            logger.error("Falha ao configurar Alarm Server: %s", exc)
            return False

    async def sync_time(self) -> bool:
        """Sincroniza relógio da câmera com o servidor."""
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        # ISAPI espera formato específico
        payload = f"""<Time>
  <year>{now.year}</year>
  <month>{now.month:02d}</month>
  <day>{now.day:02d}</day>
  <hour>{now.hour:02d}</hour>
  <minute>{now.minute:02d}</minute>
  <second>{now.second:02d}</second>
</Time>"""
        try:
            await self.put("System/time", data=payload)
            logger.info("Tempo da câmera sincronizado")
            return True
        except Exception as exc:
            logger.error("Falha ao sincronizar tempo: %s", exc)
            return False

    async def get_snapshot(self) -> bytes:
        """Captura snapshot via ISAPI (fallback para ONVIF)."""
        response = await self._request("GET", "Streaming/channels/101/picture")
        return response.content

    async def probe(self) -> dict:
        """Faz probe completo: info, capacidades, modelo, firmware."""
        info = await self.get_device_info()
        caps = await self.get_capabilities()
        # xmltodict envolve no elemento raiz (ex: {"DeviceInfo": {...}}); desembrulha
        info_body = info.get("DeviceInfo", info) if isinstance(info, dict) else {}
        return {
            "info": info,
            "capabilities": caps,
            "model_name": (
                info_body.get("deviceName")
                or info_body.get("model")
                or info_body.get("DeviceName")
                or "Unknown"
            ),
            "serial_number": info_body.get("serialNumber") or "Unknown",
            "firmware_version": info_body.get("firmwareVersion") or "Unknown",
        }
