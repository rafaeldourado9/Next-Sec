"""Cliente ONVIF leve usando zeep/WS para GetCapabilities e GetStreamUri.

Não depende de onvif-python-zeep: usa httpx com envelope SOAP raw para
manter dependências mínimas no container da API.
"""
from __future__ import annotations

import re
import asyncio
from xml.etree import ElementTree as ET

import httpx

from vms.cameras.domain import OnvifProbeResult

_SOAP_ENV = "http://www.w3.org/2003/05/soap-envelope"
_DEVICE_NS = "http://www.onvif.org/ver10/device/wsdl"
_MEDIA_NS = "http://www.onvif.org/ver10/media/wsdl"
_SCHEMA_NS = "http://www.onvif.org/ver10/schema"

_GETINFO_BODY = """<?xml version="1.0" encoding="utf-8"?>
<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope"
            xmlns:tds="http://www.onvif.org/ver10/device/wsdl">
  <s:Body>
    <tds:GetDeviceInformation/>
  </s:Body>
</s:Envelope>"""

_GETPROFILES_BODY = """<?xml version="1.0" encoding="utf-8"?>
<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope"
            xmlns:trt="http://www.onvif.org/ver10/media/wsdl">
  <s:Body>
    <trt:GetProfiles/>
  </s:Body>
</s:Envelope>"""

_GETSTREAMURI_BODY = """<?xml version="1.0" encoding="utf-8"?>
<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope"
            xmlns:trt="http://www.onvif.org/ver10/media/wsdl"
            xmlns:tt="http://www.onvif.org/ver10/schema">
  <s:Body>
    <trt:GetStreamUri>
      <trt:StreamSetup>
        <tt:Stream>RTP-Unicast</tt:Stream>
        <tt:Transport><tt:Protocol>RTSP</tt:Protocol></tt:Transport>
      </trt:StreamSetup>
      <trt:ProfileToken>{token}</trt:ProfileToken>
    </trt:GetStreamUri>
  </s:Body>
</s:Envelope>"""

_GETSNAPSHOT_BODY = """<?xml version="1.0" encoding="utf-8"?>
<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope"
            xmlns:trt="http://www.onvif.org/ver10/media/wsdl">
  <s:Body>
    <trt:GetSnapshotUri>
      <trt:ProfileToken>{token}</trt:ProfileToken>
    </trt:GetSnapshotUri>
  </s:Body>
</s:Envelope>"""


def _wsa_credentials(username: str, password: str) -> str:
    """Gera WS-Security UsernameToken (PasswordText simples — suficiente para LAN)."""
    if not username:
        return ""
    return f"""<s:Header>
    <Security xmlns="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-secext-1.0.xsd">
      <UsernameToken>
        <Username>{username}</Username>
        <Password Type="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-username-token-profile-1.0#PasswordText">{password}</Password>
      </UsernameToken>
    </Security>
  </s:Header>"""


def _inject_auth(body: str, username: str, password: str) -> str:
    """Injeta WS-Security header no envelope SOAP."""
    header = _wsa_credentials(username, password)
    if not header:
        return body
    return body.replace("<s:Body>", f"{header}\n  <s:Body>", 1)


def _find_text(root: ET.Element, *tags: str) -> str | None:
    """Busca primeiro elemento com qualquer um dos tags (ignora namespace)."""
    for elem in root.iter():
        local = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag
        if local in tags and elem.text:
            return elem.text.strip()
    return None


class OnvifClient:
    """Cliente ONVIF assíncrono para probe e descoberta."""

    @staticmethod
    async def probe(
        onvif_url: str,
        username: str,
        password: str,
        timeout: float = 5.0,
    ) -> OnvifProbeResult:
        """
        Faz probe completo: GetDeviceInformation → GetProfiles → GetStreamUri.

        Retorna OnvifProbeResult com todas as informações disponíveis.
        """
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                # 1. Device information
                info_body = _inject_auth(_GETINFO_BODY, username, password)
                info_resp = await client.post(
                    onvif_url,
                    content=info_body,
                    headers={"Content-Type": "application/soap+xml; charset=utf-8"},
                )
                manufacturer: str | None = None
                model: str | None = None
                if info_resp.status_code == 200:
                    root = ET.fromstring(info_resp.text)
                    manufacturer = _find_text(root, "Manufacturer")
                    model = _find_text(root, "Model")

                # 2. Media profiles
                media_url = onvif_url.replace("device_service", "Media")
                profiles_body = _inject_auth(_GETPROFILES_BODY, username, password)
                profiles_resp = await client.post(
                    media_url,
                    content=profiles_body,
                    headers={"Content-Type": "application/soap+xml; charset=utf-8"},
                )
                if profiles_resp.status_code != 200:
                    return OnvifProbeResult(
                        reachable=True,
                        manufacturer=manufacturer,
                        model=model,
                        error="Falha ao obter profiles de mídia",
                    )
                root = ET.fromstring(profiles_resp.text)
                profile_token = _find_text(root, "token")
                if not profile_token:
                    # tenta via atributo token
                    for elem in root.iter():
                        if elem.tag.split("}")[-1] == "Profiles" or elem.tag.split("}")[-1] == "Profile":
                            profile_token = elem.get("token")
                            if profile_token:
                                break

                if not profile_token:
                    return OnvifProbeResult(
                        reachable=True,
                        manufacturer=manufacturer,
                        model=model,
                        error="Nenhum profile de mídia encontrado",
                    )

                # 3. Stream URI
                stream_body = _inject_auth(
                    _GETSTREAMURI_BODY.format(token=profile_token), username, password
                )
                stream_resp = await client.post(
                    media_url,
                    content=stream_body,
                    headers={"Content-Type": "application/soap+xml; charset=utf-8"},
                )
                rtsp_url: str | None = None
                if stream_resp.status_code == 200:
                    root = ET.fromstring(stream_resp.text)
                    rtsp_url = _find_text(root, "Uri")

                # 4. Snapshot URI (best-effort)
                snapshot_url: str | None = None
                try:
                    snap_body = _inject_auth(
                        _GETSNAPSHOT_BODY.format(token=profile_token), username, password
                    )
                    snap_resp = await client.post(
                        media_url,
                        content=snap_body,
                        headers={"Content-Type": "application/soap+xml; charset=utf-8"},
                    )
                    if snap_resp.status_code == 200:
                        root = ET.fromstring(snap_resp.text)
                        snapshot_url = _find_text(root, "Uri")
                except Exception:
                    pass

                return OnvifProbeResult(
                    reachable=True,
                    manufacturer=manufacturer,
                    model=model,
                    rtsp_url=rtsp_url,
                    snapshot_url=snapshot_url,
                )

        except httpx.ConnectError:
            return OnvifProbeResult(reachable=False, error="Host inacessível")
        except httpx.TimeoutException:
            return OnvifProbeResult(reachable=False, error="Timeout ao conectar")
        except Exception as exc:
            return OnvifProbeResult(reachable=False, error=str(exc))

    @staticmethod
    async def discover(timeout_seconds: int = 3) -> list[dict]:
        """
        WS-Discovery broadcast para encontrar câmeras ONVIF na rede local.

        Retorna lista de dicts com 'onvif_url' e 'ip'.
        """
        import socket

        WS_DISCOVERY_ADDR = "239.255.255.250"
        WS_DISCOVERY_PORT = 3702
        PROBE_MSG = """<?xml version="1.0" encoding="utf-8"?>
<e:Envelope xmlns:e="http://www.w3.org/2003/05/soap-envelope"
            xmlns:w="http://schemas.xmlsoap.org/ws/2004/08/addressing"
            xmlns:d="http://schemas.xmlsoap.org/ws/2005/04/discovery"
            xmlns:dn="http://www.onvif.org/ver10/network/wsdl">
  <e:Header>
    <w:MessageID>uuid:b5f4b6c0-0001-0001-0001-000100010001</w:MessageID>
    <w:To>urn:schemas-xmlsoap-org:ws:2005:04:discovery</w:To>
    <w:Action>http://schemas.xmlsoap.org/ws/2005/04/discovery/Probe</w:Action>
  </e:Header>
  <e:Body>
    <d:Probe>
      <d:Types>dn:NetworkVideoTransmitter</d:Types>
    </d:Probe>
  </e:Body>
</e:Envelope>"""

        discovered: list[dict] = []
        seen_ips: set[str] = set()

        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 4)
        sock.settimeout(timeout_seconds)
        sock.sendto(PROBE_MSG.encode(), (WS_DISCOVERY_ADDR, WS_DISCOVERY_PORT))

        try:
            while True:
                data, addr = sock.recvfrom(65536)
                ip = addr[0]
                if ip in seen_ips:
                    continue
                seen_ips.add(ip)
                text = data.decode(errors="ignore")
                # Extrai XAddrs do probe match
                xaddr_match = re.search(r"<[^>]*XAddrs[^>]*>([^<]+)<", text)
                if xaddr_match:
                    xaddrs = xaddr_match.group(1).strip().split()
                    onvif_url = next(
                        (u for u in xaddrs if "onvif" in u.lower() or "device" in u.lower()),
                        xaddrs[0] if xaddrs else f"http://{ip}/onvif/device_service",
                    )
                else:
                    onvif_url = f"http://{ip}/onvif/device_service"

                discovered.append({"onvif_url": onvif_url, "ip": ip})
        except socket.timeout:
            pass
        finally:
            sock.close()

        return discovered
