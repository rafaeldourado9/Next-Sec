"""Cliente ONVIF PTZ — operações ContinuousMove, GotoPreset, Stop, SetPreset.

Usa SOAP raw via httpx, sem dependência de onvif-python ou zeep.
"""
from __future__ import annotations

import asyncio
from xml.etree import ElementTree as ET

import httpx

from vms.cameras.ptz.domain import PtzCommand, PtzPreset
from vms.shared.exceptions import ValidationError

_PTZ_NS = "http://www.onvif.org/ver20/ptz/wsdl"
_SCHEMA_NS = "http://www.onvif.org/ver10/schema"

_GET_CAPABILITIES = """<?xml version="1.0" encoding="utf-8"?>
<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope"
            xmlns:tds="http://www.onvif.org/ver10/device/wsdl">
  {auth}
  <s:Body>
    <tds:GetCapabilities>
      <tds:Category>All</tds:Category>
    </tds:GetCapabilities>
  </s:Body>
</s:Envelope>"""

_GET_PROFILES = """<?xml version="1.0" encoding="utf-8"?>
<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope"
            xmlns:trt="http://www.onvif.org/ver10/media/wsdl">
  {auth}
  <s:Body>
    <trt:GetProfiles/>
  </s:Body>
</s:Envelope>"""

_GET_PRESETS = """<?xml version="1.0" encoding="utf-8"?>
<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope"
            xmlns:tptz="http://www.onvif.org/ver20/ptz/wsdl">
  {auth}
  <s:Body>
    <tptz:GetPresets>
      <tptz:ProfileToken>{profile_token}</tptz:ProfileToken>
    </tptz:GetPresets>
  </s:Body>
</s:Envelope>"""

_GOTO_PRESET = """<?xml version="1.0" encoding="utf-8"?>
<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope"
            xmlns:tptz="http://www.onvif.org/ver20/ptz/wsdl"
            xmlns:tt="http://www.onvif.org/ver10/schema">
  {auth}
  <s:Body>
    <tptz:GotoPreset>
      <tptz:ProfileToken>{profile_token}</tptz:ProfileToken>
      <tptz:PresetToken>{preset_token}</tptz:PresetToken>
      <tptz:Speed>
        <tt:PanTilt x="{speed}" y="{speed}"/>
        <tt:Zoom x="{speed}"/>
      </tptz:Speed>
    </tptz:GotoPreset>
  </s:Body>
</s:Envelope>"""

_CONTINUOUS_MOVE = """<?xml version="1.0" encoding="utf-8"?>
<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope"
            xmlns:tptz="http://www.onvif.org/ver20/ptz/wsdl"
            xmlns:tt="http://www.onvif.org/ver10/schema">
  {auth}
  <s:Body>
    <tptz:ContinuousMove>
      <tptz:ProfileToken>{profile_token}</tptz:ProfileToken>
      <tptz:Velocity>
        <tt:PanTilt x="{pan}" y="{tilt}"/>
        <tt:Zoom x="{zoom}"/>
      </tptz:Velocity>
    </tptz:ContinuousMove>
  </s:Body>
</s:Envelope>"""

_STOP = """<?xml version="1.0" encoding="utf-8"?>
<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope"
            xmlns:tptz="http://www.onvif.org/ver20/ptz/wsdl">
  {auth}
  <s:Body>
    <tptz:Stop>
      <tptz:ProfileToken>{profile_token}</tptz:ProfileToken>
      <tptz:PanTilt>true</tptz:PanTilt>
      <tptz:Zoom>true</tptz:Zoom>
    </tptz:Stop>
  </s:Body>
</s:Envelope>"""

_SET_PRESET = """<?xml version="1.0" encoding="utf-8"?>
<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope"
            xmlns:tptz="http://www.onvif.org/ver20/ptz/wsdl">
  {auth}
  <s:Body>
    <tptz:SetPreset>
      <tptz:ProfileToken>{profile_token}</tptz:ProfileToken>
      <tptz:PresetName>{name}</tptz:PresetName>
    </tptz:SetPreset>
  </s:Body>
</s:Envelope>"""

_CONTENT_TYPE = "application/soap+xml; charset=utf-8"


def _auth_header(username: str, password: str) -> str:
    """Gera WS-Security UsernameToken para injeção no envelope SOAP."""
    if not username:
        return ""
    return (
        "<s:Header>"
        '<Security xmlns="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-secext-1.0.xsd">'
        "<UsernameToken>"
        f"<Username>{username}</Username>"
        f'<Password Type="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-username-token-profile-1.0#PasswordText">{password}</Password>'
        "</UsernameToken>"
        "</Security>"
        "</s:Header>"
    )


def _find_text(root: ET.Element, *tags: str) -> str | None:
    """Retorna texto do primeiro elemento que casa com qualquer um dos tags."""
    for elem in root.iter():
        local = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag
        if local in tags and elem.text:
            return elem.text.strip()
    return None


def _find_ptz_url(root: ET.Element) -> str | None:
    """Extrai PTZ XAddr do response de GetCapabilities."""
    for elem in root.iter():
        local = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag
        if local == "PTZ":
            for child in elem:
                child_local = child.tag.split("}")[-1] if "}" in child.tag else child.tag
                if child_local == "XAddr" and child.text:
                    return child.text.strip()
    return None


def _get_profile_token_from_root(root: ET.Element) -> str | None:
    """Extrai token do primeiro Profile do response de GetProfiles."""
    for elem in root.iter():
        local = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag
        if local in ("Profiles", "Profile"):
            token = elem.get("token")
            if token:
                return token
    return None


class PtzClient:
    """Cliente ONVIF PTZ assíncrono."""

    @staticmethod
    async def get_ptz_url(
        onvif_url: str,
        username: str,
        password: str,
        client: httpx.AsyncClient,
    ) -> str:
        """Obtém URL do serviço PTZ via GetCapabilities. Lança ValidationError se PTZ não suportado."""
        body = _GET_CAPABILITIES.format(auth=_auth_header(username, password))
        resp = await client.post(onvif_url, content=body, headers={"Content-Type": _CONTENT_TYPE})
        if resp.status_code != 200:
            raise ValidationError("Câmera não suporta PTZ ou retornou erro em GetCapabilities")
        root = ET.fromstring(resp.text)
        ptz_url = _find_ptz_url(root)
        if not ptz_url:
            raise ValidationError("Câmera não possui serviço PTZ (GetCapabilities sem PTZ XAddr)")
        return ptz_url

    @staticmethod
    async def get_profile_token(
        onvif_url: str,
        username: str,
        password: str,
        client: httpx.AsyncClient,
    ) -> str:
        """Obtém token do primeiro perfil de mídia via GetProfiles."""
        media_url = onvif_url.replace("device_service", "Media")
        body = _GET_PROFILES.format(auth=_auth_header(username, password))
        resp = await client.post(media_url, content=body, headers={"Content-Type": _CONTENT_TYPE})
        if resp.status_code != 200:
            raise ValidationError("Falha ao obter profiles de mídia para PTZ")
        root = ET.fromstring(resp.text)
        token = _get_profile_token_from_root(root)
        if not token:
            raise ValidationError("Nenhum profile de mídia encontrado para PTZ")
        return token

    @staticmethod
    async def check_ptz_supported(
        onvif_url: str,
        username: str,
        password: str,
        timeout: float = 5.0,
    ) -> bool:
        """Retorna True se a câmera suporta PTZ. Não lança exceção."""
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                await PtzClient.get_ptz_url(onvif_url, username, password, client)
            return True
        except Exception:
            return False

    @staticmethod
    async def get_presets(
        ptz_url: str,
        profile_token: str,
        username: str,
        password: str,
        client: httpx.AsyncClient,
    ) -> list[PtzPreset]:
        """Lista presets PTZ salvos na câmera."""
        body = _GET_PRESETS.format(
            auth=_auth_header(username, password),
            profile_token=profile_token,
        )
        resp = await client.post(ptz_url, content=body, headers={"Content-Type": _CONTENT_TYPE})
        if resp.status_code != 200:
            return []
        root = ET.fromstring(resp.text)
        presets: list[PtzPreset] = []
        for elem in root.iter():
            local = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag
            if local == "Preset":
                token = elem.get("token") or ""
                name: str | None = None
                for child in elem:
                    child_local = child.tag.split("}")[-1] if "}" in child.tag else child.tag
                    if child_local == "Name" and child.text:
                        name = child.text.strip()
                if token:
                    presets.append(PtzPreset(token=token, name=name))
        return presets

    @staticmethod
    async def goto_preset(
        ptz_url: str,
        profile_token: str,
        preset_token: str,
        speed: float,
        username: str,
        password: str,
        client: httpx.AsyncClient,
    ) -> None:
        """Move câmera para posição de preset salvo."""
        body = _GOTO_PRESET.format(
            auth=_auth_header(username, password),
            profile_token=profile_token,
            preset_token=preset_token,
            speed=round(max(0.0, min(1.0, speed)), 2),
        )
        resp = await client.post(ptz_url, content=body, headers={"Content-Type": _CONTENT_TYPE})
        if resp.status_code not in (200, 204):
            raise ValidationError(f"GotoPreset falhou: HTTP {resp.status_code}")

    @staticmethod
    async def continuous_move(
        ptz_url: str,
        profile_token: str,
        command: PtzCommand,
        username: str,
        password: str,
        client: httpx.AsyncClient,
    ) -> None:
        """Inicia movimento contínuo pan/tilt/zoom."""
        body = _CONTINUOUS_MOVE.format(
            auth=_auth_header(username, password),
            profile_token=profile_token,
            pan=round(max(-1.0, min(1.0, command.pan)), 4),
            tilt=round(max(-1.0, min(1.0, command.tilt)), 4),
            zoom=round(max(-1.0, min(1.0, command.zoom)), 4),
        )
        resp = await client.post(ptz_url, content=body, headers={"Content-Type": _CONTENT_TYPE})
        if resp.status_code not in (200, 204):
            raise ValidationError(f"ContinuousMove falhou: HTTP {resp.status_code}")

    @staticmethod
    async def stop(
        ptz_url: str,
        profile_token: str,
        username: str,
        password: str,
        client: httpx.AsyncClient,
    ) -> None:
        """Para qualquer movimento PTZ em curso."""
        body = _STOP.format(
            auth=_auth_header(username, password),
            profile_token=profile_token,
        )
        resp = await client.post(ptz_url, content=body, headers={"Content-Type": _CONTENT_TYPE})
        if resp.status_code not in (200, 204):
            raise ValidationError(f"Stop PTZ falhou: HTTP {resp.status_code}")

    @staticmethod
    async def set_preset(
        ptz_url: str,
        profile_token: str,
        name: str,
        username: str,
        password: str,
        client: httpx.AsyncClient,
    ) -> str:
        """Salva posição atual como preset. Retorna token do preset criado."""
        body = _SET_PRESET.format(
            auth=_auth_header(username, password),
            profile_token=profile_token,
            name=name,
        )
        resp = await client.post(ptz_url, content=body, headers={"Content-Type": _CONTENT_TYPE})
        if resp.status_code not in (200, 204):
            raise ValidationError(f"SetPreset falhou: HTTP {resp.status_code}")
        root = ET.fromstring(resp.text)
        token = _find_text(root, "PresetToken")
        if not token:
            raise ValidationError("SetPreset não retornou PresetToken")
        return token
