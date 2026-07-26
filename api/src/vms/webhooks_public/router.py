"""Webhook público para câmeras IP enviarem eventos diretamente.

Sem autenticação — câmeras não suportam JWT.
Identificação da câmera por (em ordem de prioridade):
  1. Query param ?camera_id=<uuid>  ← mais confiável, configure na URL do alarm server
  2. Campo 'camera_id'/'deviceId' no payload
  3. Stream key no payload (path live/xxx)
  4. Campo 'ipAddress' no XML do payload
  5. IP de origem da requisição → match com rtsp_url/onvif_url no DB

Endpoints expostos pelo nginx em:
  /hik_pro_connect          → alias direto (sem prefixo, compatível com config de câmera)
  /intelbras_events         → alias direto
  /webhooks/hik_pro_connect → com prefixo (ambos funcionam)
  /webhooks/intelbras_events
  /webhooks/camera_events
"""
from __future__ import annotations

import json
import logging
import os
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

from fastapi import APIRouter, Query, Request, status
from sqlalchemy import select

from vms.cameras.models import CameraModel
from vms.infrastructure.database import get_session_factory, get_db_context
from vms.events.models import VmsEventModel
from vms.events.normalizers.base import registry
from vms.shared.api.rate_limit import limiter

logger = logging.getLogger(__name__)

# Auto-registra normalizers ao importar
import vms.events.normalizers.hikvision  # noqa: F401
import vms.events.normalizers.intelbras  # noqa: F401
import vms.events.normalizers.generic    # noqa: F401

router = APIRouter()

_STREAM_KEY_RE = re.compile(r"live/(?P<key>[a-zA-Z0-9_\-\.]+?)(?:\.stream)?$")


# ─── Body parsing ─────────────────────────────────────────────────────────────
# Hikvision "Alarm Server" envia multipart/form-data com JSON na parte
# 'anpr_result', OU application/xml (ISAPI EventNotificationAlert).
# O código antigo fazia request.json() que falha silenciosamente → body={}.

async def _parse_body(request: Request) -> dict:
    """
    Parseia o body independente do Content-Type.

    Tenta, em ordem:
    1. multipart/form-data  — Hikvision alarm server (formato principal)
    2. application/xml      — Hikvision ISAPI / Intelbras XML
    3. application/json     — maioria dos fabricantes
    4. fallback: tenta JSON, depois XML
    """
    ct = request.headers.get("content-type", "").lower()

    if os.getenv("VMS_LOG_RAW_WEBHOOKS"):
        try:
            raw_preview = (await request.body())[:2048]
            logger.info(
                "RAW webhook | path=%s ct=%s ua=%s headers=%s body[0:2k]=%r",
                request.url.path,
                ct,
                request.headers.get("user-agent", "?"),
                dict(request.headers),
                raw_preview,
            )
        except Exception as exc:
            logger.debug("Falha ao logar raw webhook: %s", exc)

    if "multipart" in ct:
        return await _parse_multipart(request)

    raw = await request.body()
    if not raw:
        return {}

    if "xml" in ct:
        return _parse_xml(raw)

    # JSON ou Content-Type ausente/desconhecido
    try:
        result = json.loads(raw)
        return result if isinstance(result, dict) else {}
    except (json.JSONDecodeError, UnicodeDecodeError):
        # Último recurso: tenta XML
        try:
            return _parse_xml(raw)
        except ET.ParseError:
            return {}


async def _parse_multipart(request: Request) -> dict:
    """
    Extrai payload JSON do multipart enviado pela Hikvision.

    A Hikvision coloca o JSON em campos nomeados:
      'anpr_result'  → payload ANPR
      'event_info'   → evento genérico
      'alarmEvent'   → evento de alarme
    Campos binários (imagem JPEG) são ignorados.
    """
    try:
        form = await request.form()

        # Campos conhecidos da Hikvision (em ordem de preferência)
        for field in ("anpr_result", "event_info", "alarmEvent", "data", "payload"):
            val = form.get(field)
            if val and isinstance(val, str):
                try:
                    parsed = json.loads(val)
                    if isinstance(parsed, dict):
                        return parsed
                except (json.JSONDecodeError, ValueError):
                    pass

        # Qualquer campo string que pareça JSON
        for _name, val in form.multi_items():
            if isinstance(val, str) and val.strip().startswith("{"):
                try:
                    parsed = json.loads(val)
                    if isinstance(parsed, dict):
                        return parsed
                except (json.JSONDecodeError, ValueError):
                    pass

        # Fallback: campos simples como dict
        return {k: v for k, v in form.multi_items() if isinstance(v, str)}

    except Exception as exc:
        logger.debug("Falha ao parsear multipart: %s", exc)
        return {}


def _parse_xml(xml_bytes: bytes) -> dict:
    """
    Converte XML Hikvision EventNotificationAlert para dict normalizado.

    Entrada:
        <EventNotificationAlert>
            <ANPR>
                <licensePlate>ABC1234</licensePlate>
                <confidence>85</confidence>
            </ANPR>
            <dateTime>2026-04-11T10:58:07+01:00</dateTime>
            <ipAddress>192.168.1.64</ipAddress>
        </EventNotificationAlert>

    Saída:
        {
            "ANPR": {"licensePlate": "ABC1234", "confidence": "85"},
            "dateTime": "2026-04-11T10:58:07+01:00",
            "ipAddress": "192.168.1.64",
        }
    """
    root = ET.fromstring(xml_bytes)  # lança ET.ParseError se inválido
    result = _elem_to_dict(root)
    # Achata o wrapper raiz (ex: EventNotificationAlert) para o dict interior
    root_tag = root.tag.split("}")[-1] if "}" in root.tag else root.tag
    if root_tag in result and isinstance(result[root_tag], dict):
        return result[root_tag]
    return result


def _elem_to_dict(el: ET.Element) -> dict:
    """
    Converte elemento XML em {tag: value} recursivamente, stripando namespaces.

    - Elemento folha  → {tag: "texto"}
    - Elemento pai    → {tag: {child_tag: child_value, ...}}
    - Tags duplicadas → {tag: [val1, val2, ...]}
    """
    tag = el.tag.split("}")[-1] if "}" in el.tag else el.tag
    children = list(el)

    if not children:
        return {tag: (el.text or "").strip()}

    child_dict: dict = {}
    for child in children:
        child_tag = child.tag.split("}")[-1] if "}" in child.tag else child.tag
        # Desempacota o valor filho (retorna {child_tag: val})
        child_val = _elem_to_dict(child).get(child_tag)

        if child_tag in child_dict:
            existing = child_dict[child_tag]
            if not isinstance(existing, list):
                child_dict[child_tag] = [existing]
            child_dict[child_tag].append(child_val)
        else:
            child_dict[child_tag] = child_val

    return {tag: child_dict}


# ─── Camera resolution ────────────────────────────────────────────────────────

def _get_real_ip(request: Request) -> str:
    """
    Extrai o IP real do cliente em ordem de confiabilidade:
    1. CF-Connecting-IP  — cabeçalho oficial Cloudflare (IP do cliente final)
    2. X-Forwarded-For   — primeiro IP da cadeia (antes de proxies internos)
    3. X-Real-IP         — setado pelo nginx (pode ser IP do proxy interno)
    4. request.client    — fallback direto
    """
    return (
        request.headers.get("CF-Connecting-IP")
        or request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
        or request.headers.get("X-Real-IP")
        or (request.client.host if request.client else "")
    )


async def _resolve_camera(
    body: dict,
    remote_ip: str,
    camera_id_param: str | None = None,
) -> tuple[str, str] | None:
    """
    Resolve (tenant_id, camera_id) em ordem de confiabilidade:

    1. ?camera_id= query param  — integrador configurou na URL
    2. Campo camera_id/deviceId no body
    3. Serial extraído do JPEG Intelbras ITSCAM
    4. Stream key live/<key>
    5. Campo ipAddress no XML (câmera Hikvision inclui <ipAddress>)
    6. IP de origem → match com rtsp_url / onvif_url no DB
    """
    # 1. Query param — mais confiável
    if camera_id_param:
        result = await _lookup_by_id(camera_id_param)
        if result:
            logger.debug("Câmera resolvida via query param: %s", camera_id_param)
            return result

    # 2. Campo direto no body (top-level)
    for key in ("camera_id", "cameraId", "DeviceID", "deviceId", "device_id", "deviceSerial", "serialNo"):
        cam_id = body.get(key)
        if cam_id and isinstance(cam_id, str):
            result = await _lookup_by_id(str(cam_id))
            if result:
                logger.debug("Câmera resolvida via body[%s]: %s", key, cam_id)
                return result

    # 2b. Intelbras ITSCAM — DeviceID em Picture.SnapInfo.DeviceID
    #     O campo "Nº dispos." da câmera é enviado nesse path aninhado
    snap_device_id = (
        body.get("Picture", {}).get("SnapInfo", {}).get("DeviceID")
        if isinstance(body.get("Picture"), dict)
        else None
    )
    if snap_device_id and isinstance(snap_device_id, str):
        result = await _lookup_by_id(snap_device_id)
        if result:
            logger.debug("Câmera resolvida via Picture.SnapInfo.DeviceID: %s", snap_device_id)
            return result

    # 3. Serial embutido no JPEG Intelbras ITSCAM
    serial = _extract_intelbras_serial(body)
    if serial:
        result = await _lookup_by_serial(serial)
        if result:
            logger.debug("Câmera resolvida via serial Intelbras: %s", serial)
            return result
        logger.debug("Serial Intelbras extraído mas não encontrado no DB: %s", serial)

    # 4. Stream key
    path = body.get("path", body.get("stream_key", ""))
    if m := _STREAM_KEY_RE.match(str(path)):
        result = await _lookup_by_stream_key(m.group("key"))
        if result:
            logger.debug("Câmera resolvida via stream_key: %s", m.group("key"))
            return result

    # 5. IP no payload XML
    payload_ip = body.get("ipAddress", "")
    if payload_ip and payload_ip != remote_ip:
        result = await _lookup_by_ip(str(payload_ip))
        if result:
            logger.debug("Câmera resolvida via ipAddress no payload: %s", payload_ip)
            return result

    # 6. IP de origem
    if remote_ip:
        result = await _lookup_by_ip(remote_ip)
        if result:
            logger.debug("Câmera resolvida via IP de origem: %s", remote_ip)
            return result

    return None


async def _lookup_by_id(cam_id: str) -> tuple[str, str] | None:
    factory = get_session_factory()
    async with factory() as session:
        cam = await session.scalar(
            select(CameraModel).where(
                CameraModel.id == cam_id,
                CameraModel.is_active.is_(True),
            )
        )
        return (cam.tenant_id, cam.id) if cam else None


async def _lookup_by_stream_key(stream_key: str) -> tuple[str, str] | None:
    factory = get_session_factory()
    async with factory() as session:
        cam = await session.scalar(
            select(CameraModel).where(
                CameraModel.rtmp_stream_key == stream_key,
                CameraModel.is_active.is_(True),
            )
        )
        return (cam.tenant_id, cam.id) if cam else None


async def _lookup_by_serial(serial: str) -> tuple[str, str] | None:
    """Busca câmera pelo serial number (Intelbras ITSCAM embeds serial in JPEG)."""
    if not serial:
        return None
    factory = get_session_factory()
    async with factory() as session:
        cam = await session.scalar(
            select(CameraModel).where(
                CameraModel.serial_number == serial,
                CameraModel.is_active.is_(True),
            )
        )
        return (cam.tenant_id, cam.id) if cam else None


def _extract_intelbras_serial(body: dict) -> str | None:
    """
    Extrai serial number do JPEG Intelbras ITSCAM.

    O JPEG enviado pela câmera contém metadados proprietários embutidos
    nos primeiros bytes do binário. O serial pode estar cercado por bytes
    não-imprimíveis (null-separated), então buscamos no raw bytes diretamente.
    Serial ex: OHM1400095CU, VHD3230, ITSCAM, etc.
    """
    try:
        import base64
        content = (
            body.get("Picture", {}).get("NormalPic", {}).get("Content")
            or body.get("Picture", {}).get("Content")
        )
        if not content:
            return None
        raw = base64.b64decode(content)
        # Busca nos primeiros 8KB onde estão os metadados Intelbras
        # Busca direta no raw bytes — serial pode estar entre bytes não-imprimíveis
        matches = re.findall(rb'[A-Z]{2,5}[0-9]{4,}[A-Z0-9]{0,6}', raw[:8192])
        if matches:
            logger.debug(
                "Candidatos a serial Intelbras: %s",
                [m.decode("ascii", errors="ignore") for m in matches[:10]],
            )
        for m in matches:
            text = m.decode("ascii", errors="ignore")
            if 8 <= len(text) <= 20:
                logger.debug("Serial Intelbras extraído: %s", text)
                return text
    except Exception as exc:
        logger.debug("Falha ao extrair serial Intelbras: %s", exc)
    return None


async def _lookup_by_ip(ip: str) -> tuple[str, str] | None:
    """Busca câmera que contenha o IP em rtsp_url ou onvif_url."""
    if not ip:
        return None
    factory = get_session_factory()
    async with factory() as session:
        cams = await session.scalars(
            select(CameraModel).where(CameraModel.is_active.is_(True))
        )
        for cam in cams.all():
            for url in (cam.rtsp_url, cam.onvif_url):
                if url and ip in url:
                    return cam.tenant_id, cam.id
    return None


async def _store_event(
    tenant_id: str,
    camera_id: str,
    event_type: str,
    payload: dict,
    plate: str | None = None,
    confidence: float | None = None,
) -> VmsEventModel | None:
    factory = get_session_factory()
    async with factory() as session:
        event = VmsEventModel(
            tenant_id=tenant_id,
            camera_id=camera_id,
            event_type=event_type,
            plate=plate,
            confidence=confidence,
            payload=payload,
            occurred_at=datetime.now(timezone.utc),
        )
        session.add(event)
        await session.flush()
        await session.refresh(event)
        await session.commit()
        return event


async def _publish_sse(tenant_id: str, event_type: str, data: dict) -> None:
    """Publica evento no canal SSE do tenant."""
    try:
        from vms.infrastructure.messaging.event_bus import publish_event
        await publish_event(event_type, data, tenant_id=tenant_id)
    except Exception as exc:
        logger.debug("Falha ao publicar SSE (não crítico): %s", exc)


# ─── Hikvision ───────────────────────────────────────────────────────────────

async def _handle_hikvision(request: Request, camera_id: str | None) -> dict:
    """Lógica compartilhada entre todas as rotas Hikvision (path custom + ISAPI defaults)."""
    body = await _parse_body(request)
    remote_ip = _get_real_ip(request)

    logger.info(
        "Hikvision webhook | ip=%s camera_id_param=%s ct=%s body_keys=%s",
        remote_ip,
        camera_id,
        request.headers.get("content-type", "?"),
        list(body.keys()) if body else "empty",
    )

    cam_info = await _resolve_camera(body, remote_ip, camera_id)
    if not cam_info:
        logger.warning(
            "Câmera não identificada no webhook Hikvision | ip=%s body_keys=%s",
            remote_ip,
            list(body.keys()),
        )
        # Retorna 200 para a câmera não entrar em retry loop agressivo
        return {
            "ok": False,
            "reason": "camera_not_found",
            "hint": "Add ?camera_id=<uuid> to the Alarm Server URL",
        }

    tenant_id, cam_id = cam_info

    # Tenta normalizar como ANPR e usa EventService com dedup Redis
    normalizer = registry.get("hikvision")
    if normalizer and normalizer.can_handle(body):
        try:
            detection = normalizer.normalize(body, cam_id, tenant_id)

            # Usa EventService.ingest_alpr() para dedup Redis + publish
            from vms.events.service import EventService
            from vms.events.repository import EventRepository

            async with get_db_context() as session:
                svc = EventService(EventRepository(session))
                event = await svc.ingest_alpr(detection, request.app.state.redis)

            if event is None:
                # Duplicata ignorada pelo dedup
                logger.debug(
                    "ANPR Hikvision duplicata ignorada: placa=%s camera=%s",
                    detection.plate,
                    cam_id,
                )
                return {"ok": True, "event_id": None, "dedup": True}

            logger.info("ANPR Hikvision | placa=%s camera=%s", detection.plate, cam_id)
            return {"ok": True, "event_id": event.id}
        except Exception as exc:
            logger.error("Erro ao normalizar ANPR Hikvision: %s", exc)

    # Evento genérico (motion, alarm, etc.)
    event_type = "hikvision_event"
    if body.get("eventType"):
        event_type = f"hikvision_{body['eventType']}"
    elif body.get("EventNotificationAlert", {}).get("eventType"):  # type: ignore[union-attr]
        event_type = f"hikvision_{body['EventNotificationAlert']['eventType']}"

    event = await _store_event(tenant_id, cam_id, event_type=event_type, payload=body)
    # Publica SSE para evento genérico
    await _publish_sse(tenant_id, event_type, {
        "camera_id": cam_id,
        "event_id": str(event.id) if event else None,
    })
    return {"ok": True, "event_id": str(event.id) if event else None}


@router.post(
    "/hik_pro_connect",
    status_code=status.HTTP_200_OK,
    summary="Webhook Hikvision Alarm Server",
    tags=["webhooks-public"],
)
@router.post("/Event", status_code=status.HTTP_200_OK, include_in_schema=False)
@router.post("/Event/notification/alertStream", status_code=status.HTTP_200_OK, include_in_schema=False)
@router.post("/ISAPI/Event/notification/alertStream", status_code=status.HTTP_200_OK, include_in_schema=False)
@router.post("/EventNotificationAlert", status_code=status.HTTP_200_OK, include_in_schema=False)
@limiter.limit("100/minute")
async def hikvision_webhook(
    request: Request,
    camera_id: str | None = Query(
        None,
        description=(
            "UUID da câmera (configure na URL do Alarm Server). "
            "Exemplo: /hik_pro_connect?camera_id=<uuid>"
        ),
    ),
) -> dict:
    """
    Recebe notificações do Alarm Server Hikvision.

    **Como configurar na câmera:**
    Configuração → Evento → Definição do Alarme → Servidor de Alarme:
    - IP/Host: `<seu-dominio>`
    - URL:     `/hik_pro_connect?camera_id=<uuid-da-camera>`
    - Porta:   `80`
    - Protocolo: `HTTP`

    Aceita também os paths default do firmware ISAPI (`/Event`,
    `/ISAPI/Event/notification/alertStream`, `/EventNotificationAlert`)
    para câmeras antigas que não permitem URL custom.

    Suporta: multipart/form-data, application/xml, application/json.
    """
    return await _handle_hikvision(request, camera_id)


# ─── Intelbras ────────────────────────────────────────────────────────────────

def _itscam_ok(body: dict | None = None, device_id: str | None = None) -> dict:
    """
    Resposta no formato exigido pelo firmware ITSCAM/Dahua ITCPUSH.

    A câmera espera literalmente {"Result": true, "DeviceID": "<id>"}; qualquer
    outro shape faz o firmware considerar a entrega falha e retransmitir o
    mesmo evento eternamente. Mesma exigência vale para /KeepAlive.
    """
    if device_id is None and isinstance(body, dict):
        snap = body.get("Picture", {}).get("SnapInfo", {}) if isinstance(body.get("Picture"), dict) else {}
        if isinstance(snap, dict):
            device_id = snap.get("DeviceID") or snap.get("DeviceId") or ""
    return {"Result": True, "DeviceID": device_id or ""}


@router.post(
    "/intelbras_keepalive",
    status_code=status.HTTP_200_OK,
    summary="ITSCAM KeepAlive (Dahua ITCPUSH)",
    tags=["webhooks-public"],
)
@limiter.limit("600/minute")
async def intelbras_keepalive(request: Request) -> dict:
    """
    Heartbeat periódico do firmware ITSCAM. Sem resposta no shape correto
    a câmera marca o servidor como offline e dispara replay de eventos.
    Path original na câmera: /NotificationInfo/KeepAlive (roteado pelo nginx).
    """
    try:
        body = await _parse_body(request)
    except Exception:
        body = {}
    return _itscam_ok(body)


@router.post(
    "/intelbras_events/{camera_id}",
    status_code=status.HTTP_200_OK,
    summary="Webhook Intelbras (camera_id no path)",
    tags=["webhooks-public"],
)
@router.post(
    "/intelbras_events",
    status_code=status.HTTP_200_OK,
    summary="Webhook Intelbras",
    tags=["webhooks-public"],
)
@limiter.limit("100/minute")
async def intelbras_webhook(
    request: Request,
    camera_id: str | None = None,
) -> dict:
    """
    Recebe eventos de câmeras/DVR/NVR Intelbras.

    **Como configurar (Função Push → campo Cliente):**
    - URL com path: `https://<dominio>/intelbras_events/<uuid-da-camera>`
    - URL com query param: `https://<dominio>/intelbras_events?camera_id=<uuid>`
    """
    # camera_id pode vir do path param ou do query param
    if camera_id is None:
        camera_id = request.query_params.get("camera_id")
    body = await _parse_body(request)
    remote_ip = _get_real_ip(request)

    pic = body.get("Picture", {}) if isinstance(body.get("Picture"), dict) else {}
    pic_name = pic.get("NormalPic", {}).get("PicName", "") if isinstance(pic.get("NormalPic"), dict) else ""
    logger.info(
        "Intelbras webhook | ip=%s camera_id_param=%s pic_name=%s",
        remote_ip,
        camera_id,
        pic_name or "(sem pic_name)",
    )

    cam_info = await _resolve_camera(body, remote_ip, camera_id)
    if not cam_info:
        # Mesmo sem identificar a câmera, responde no shape ITSCAM para a câmera
        # parar de retransmitir o mesmo evento. Loga warning para diagnóstico.
        logger.warning("Câmera não identificada no webhook Intelbras | ip=%s", remote_ip)
        return _itscam_ok(body)

    tenant_id, cam_id = cam_info

    normalizer = registry.get("intelbras")
    if normalizer and normalizer.can_handle(body):
        try:
            detection = normalizer.normalize(body, cam_id, tenant_id)

            # normalize() retorna None quando não há placa detectada (ex: Desconhecido)
            if detection is None:
                logger.debug("Intelbras ITSCAM: frame sem placa detectada — ignorando")
                return _itscam_ok(body)

            # Usa EventService.ingest_alpr() para dedup Redis + publish
            from vms.events.service import EventService
            from vms.events.repository import EventRepository

            async with get_db_context() as session:
                svc = EventService(EventRepository(session))
                event = await svc.ingest_alpr(detection, request.app.state.redis)

            if event is None:
                logger.debug(
                    "ANPR Intelbras duplicata ignorada: placa=%s camera=%s",
                    detection.plate,
                    cam_id,
                )
                return _itscam_ok(body)

            logger.info("ANPR Intelbras | placa=%s camera=%s", detection.plate, cam_id)
            return _itscam_ok(body)
        except Exception as exc:
            logger.error("Erro ao normalizar Intelbras ALPR: %s", exc)
            return _itscam_ok(body)

    # Tenta Smart Events Intelbras
    smart_normalizer = registry.get("intelbras_smart")
    if smart_normalizer and smart_normalizer.can_handle(body):
        try:
            detection = smart_normalizer.normalize(body, cam_id, tenant_id)
            # Salva como VmsEvent genérico (não é ALPR, logo não precisa de dedup de placa)
            await _store_event(
                tenant_id, cam_id,
                event_type=detection.raw_payload.get("event") or "intelbras_smart_event",
                payload=detection.raw_payload,
                confidence=detection.confidence or None,
            )
            logger.info("Smart Event Intelbras | tipo=%s camera=%s", detection.raw_payload.get("event"), cam_id)
            return _itscam_ok(body)
        except Exception as exc:
            logger.error("Erro ao normalizar Smart Event Intelbras: %s", exc)
            return _itscam_ok(body)

    # Fallback genérico — não salvar se o payload for só JPEG sem campos úteis
    if body.get("Picture") and not body.get("plate") and not body.get("placa") and not body.get("Events"):
        logger.debug("Intelbras: payload Picture sem metadados úteis — ignorando fallback")
        return _itscam_ok(body)

    event_type = f"intelbras_{body.get('eventType', body.get('type', body.get('event', 'event')))}"
    plate = body.get("plate") or body.get("licensePlate") or body.get("placa")
    confidence = body.get("confidence") or body.get("confianca")

    event = await _store_event(
        tenant_id, cam_id,
        event_type=event_type,
        payload=body,
        plate=str(plate) if plate else None,
        confidence=float(confidence) if confidence else None,
    )
    # Publica SSE para evento genérico
    await _publish_sse(tenant_id, event_type, {
        "camera_id": cam_id,
        "plate": plate,
        "event_id": str(event.id) if event else None,
    })
    return _itscam_ok(body)


# ─── Genérico ────────────────────────────────────────────────────────────────

@router.post(
    "/camera_events",
    status_code=status.HTTP_200_OK,
    summary="Webhook genérico",
    tags=["webhooks-public"],
)
@limiter.limit("100/minute")
async def generic_camera_webhook(
    request: Request,
    camera_id: str | None = Query(None),
) -> dict:
    """Endpoint genérico para qualquer câmera/fabricante."""
    body = await _parse_body(request)
    remote_ip = _get_real_ip(request)

    cam_info = await _resolve_camera(body, remote_ip, camera_id)
    if not cam_info:
        logger.warning("Câmera não identificada em camera_events | ip=%s", remote_ip)
        return {"ok": False, "reason": "camera_not_found"}

    tenant_id, cam_id = cam_info

    for mfr, normalizer in registry._normalizers.items():
        if normalizer.can_handle(body):
            try:
                detection = normalizer.normalize(body, cam_id, tenant_id)

                # Usa EventService.ingest_alpr() para dedup Redis + publish
                from vms.events.service import EventService
                from vms.events.repository import EventRepository

                async with get_db_context() as session:
                    svc = EventService(EventRepository(session))
                    event = await svc.ingest_alpr(detection, request.app.state.redis)

                if event is None:
                    return {"ok": True, "manufacturer": mfr, "event_id": None, "dedup": True}

                return {"ok": True, "manufacturer": mfr, "event_id": event.id}
            except Exception as exc:
                logger.error("Erro ao normalizar %s: %s", mfr, exc)

    event_type = body.get("eventType", body.get("type", "camera_event"))
    plate = body.get("plate") or body.get("licensePlate")
    confidence = body.get("confidence")

    event = await _store_event(
        tenant_id, cam_id,
        event_type=f"camera_{event_type}",
        payload=body,
        plate=str(plate) if plate else None,
        confidence=float(confidence) if confidence else None,
    )
    # Publica SSE para evento genérico
    await _publish_sse(tenant_id, f"camera_{event_type}", {
        "camera_id": cam_id,
        "plate": plate,
        "event_id": str(event.id) if event else None,
    })
    return {"ok": True, "event_id": str(event.id) if event else None}


# ─── Health Check ─────────────────────────────────────────────────────────────

@router.get(
    "/webhooks/health",
    summary="Health check para webhooks públicos",
    tags=["webhooks-public"],
)
async def webhooks_health() -> dict:
    """
    Retorna status dos normalizers, Redis e DB.

    Uso: GET /webhooks/health
    """
    from vms.infrastructure.database import get_session_factory
    from sqlalchemy import text

    # Verifica normalizers registrados
    normalizers = list(registry._normalizers.keys())

    # Verifica DB
    db_status = "error"
    try:
        factory = get_session_factory()
        async with factory() as session:
            await session.execute(text("SELECT 1"))
            db_status = "ok"
    except Exception:
        pass

    return {
        "status": "ok" if db_status == "ok" else "degraded",
        "normalizers": normalizers,
        "normalizer_count": len(normalizers),
        "database": db_status,
    }
