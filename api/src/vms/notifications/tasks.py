"""Tarefas ARQ para dispatch assíncrono de notificações."""
from __future__ import annotations

import logging

from vms.infrastructure.database import get_session_factory
from vms.notifications.repository import NotificationRuleRepository
from vms.notifications.dispatcher import dispatch_webhook
from vms.notifications.repository import NotificationLogRepository

logger = logging.getLogger(__name__)


async def task_dispatch_notification(
    ctx: dict,
    rule_id: str,
    event_type: str,
    event_id: str,
    payload: dict,
) -> None:
    """
    Envia webhook para uma regra de notificação.

    Busca a regra no banco, invoca o dispatcher e persiste o log resultante.
    """
    factory = get_session_factory()
    async with factory() as session:
        try:
            rule_repo = NotificationRuleRepository(session)
            # Busca a regra sem filtrar por tenant — o rule_id é suficiente aqui
            # pois a tarefa é enfileirada internamente com IDs confiáveis
            from sqlalchemy import select
            from vms.notifications.models import NotificationRuleModel
            stmt = select(NotificationRuleModel).where(
                NotificationRuleModel.id == rule_id
            )
            model = await session.scalar(stmt)
            if not model:
                logger.warning("Regra não encontrada para dispatch: %s", rule_id)
                return

            from vms.notifications.domain import NotificationRule
            rule = NotificationRule(
                id=model.id,
                tenant_id=model.tenant_id,
                name=model.name,
                event_type_pattern=model.event_type_pattern,
                destination_url=model.destination_url,
                webhook_secret=model.webhook_secret,
                is_active=model.is_active,
                created_at=model.created_at,
            )

            log = await dispatch_webhook(
                rule,
                event_type,
                event_id,
                payload,
                client=ctx.get("http_client"),
            )
            log_repo = NotificationLogRepository(session)
            await log_repo.create(log)
            await session.commit()

            logger.info(
                "Webhook despachado: rule=%s event=%s status=%s",
                rule_id, event_id, log.status,
            )
        except Exception as exc:
            await session.rollback()
            logger.exception("Erro ao despachar notificação: rule=%s event=%s", rule_id, event_id)
            # Registra falha na DLQ
            try:
                from vms.infrastructure.messaging import record_failure
                job_id = ctx.get("job_id", f"{rule_id}:{event_id}")
                await record_failure(
                    ctx["redis"],
                    "task_dispatch_notification",
                    str(job_id),
                    str(exc),
                )
            except Exception:
                pass
            raise


def _draw_bbox_overlay(image_bytes: bytes, bbox: list, bbox_unit: str | None = None) -> bytes:
    """Desenha o retângulo vermelho ao redor do bbox só na cópia enviada por
    WhatsApp — o arquivo em disco fica limpo (ver
    `analytics/core/orchestrator.py::_save_snapshot`), pois a box gravada nos
    pixels atrapalhava o "Analisar Evento" (GFPGAN não achava rosto com a
    linha cruzando o sujeito). O frontend desenha a box como overlay CSS; o
    WhatsApp não tem como fazer isso, então precisa vir já gravada na imagem.

    `bbox_unit`: "pixel" (ex.: BoundingBox do ITSCAM Intelbras, relativo à
    resolução do próprio JPEG) ou None/ausente (normalizado 0.0-1.0, usado
    pelo analytics/ — intrusion, face_recognition). Formatos diferentes,
    mesma função, pra não duplicar o desenho do retângulo em dois lugares.
    """
    import cv2
    import numpy as np

    arr = np.frombuffer(image_bytes, dtype=np.uint8)
    frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if frame is None or len(bbox) != 4:
        return image_bytes
    h, w = frame.shape[:2]
    x1, y1, x2, y2 = bbox
    if bbox_unit == "pixel":
        pt1 = (max(0, int(x1)), max(0, int(y1)))
        pt2 = (min(w - 1, int(x2)), min(h - 1, int(y2)))
    else:
        pt1 = (max(0, int(x1 * w)), max(0, int(y1 * h)))
        pt2 = (min(w - 1, int(x2 * w)), min(h - 1, int(y2 * h)))
    thickness = max(2, round(min(w, h) / 300))
    cv2.rectangle(frame, pt1, pt2, (0, 0, 255), thickness)
    ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 95])
    if not ok:
        return image_bytes
    return buf.tobytes()


_EVENT_TITLES = {
    "analytics.intrusion.crossed": "🚨 Cerca Virtual",
    "analytics.face.recognized": "👤 Reconhecimento Facial",
    "alpr_detected": "🚗 Placa Detectada",
    "analytics.speed.measured": "🚗💨 Velocidade Estimada",
}
_CLASS_LABELS = {
    "person": "Pessoa",
    "car": "Veículo",
    "motorcycle": "Moto",
    "bus": "Ônibus",
    "truck": "Caminhão",
    "bicycle": "Bicicleta",
}
_DIRECTION_LABELS = {
    "enter": "entrou na área",
    "exit": "saiu da área",
}


def _build_friendly_message(
    event_type: str,
    payload: dict,
    camera_name: str | None,
) -> str:
    """Monta a mensagem de notificação legível — antes era literalmente
    o event_type cru (ex.: "Alerta Next Sec: analytics.intrusion.crossed
    detectado"), o que não diz nada útil pra quem recebe (achado: usuário
    reportou que a mensagem chegava mas o texto era ilegível).
    """
    lines = [_EVENT_TITLES.get(event_type, "🔔 Alerta Next Sec")]
    if camera_name:
        lines.append(f"Câmera: {camera_name}")
    plate = payload.get("plate")
    if plate:
        lines.append(f"Placa: {plate}")
    roi_name = payload.get("roi_name")
    if roi_name:
        lines.append(f"Zona: {roi_name}")
    cls = _CLASS_LABELS.get(payload.get("class"), payload.get("class"))
    direction = _DIRECTION_LABELS.get(payload.get("direction"))
    if cls and direction:
        lines.append(f"{cls} {direction}")
    speed_kmh = payload.get("speed_kmh")
    if speed_kmh is not None:
        lines.append(f"{cls or 'Veículo'}: {speed_kmh} km/h")
    confidence = payload.get("confidence")
    if confidence is not None:
        lines.append(f"Confiança: {round(float(confidence) * 100)}%")
    return "\n".join(lines)


async def task_dispatch_event_notifications(
    ctx: dict,
    tenant_id: str,
    event_type: str,
    event_id: str,
    payload: dict,
    snapshot_path: str | None,
    camera_id: str | None = None,
) -> None:
    """Gera clipe (best-effort) e dispara notificações de contato (WhatsApp/etc)
    pra um evento de analytics — em background, fora do request de ingestão.

    Antes rodava tudo síncrono dentro de POST /plugins/events (ver
    plugins/router.py) — cada notificação pode envolver retries lentos (ex.:
    número com erro do lado do WhatsApp faz 3 tentativas com backoff, ~3.5s),
    e isso atrasava o evento aparecer em tempo real pro usuário mesmo o
    registro em si sendo instantâneo (achado: usuário reportou demora
    perceptível). Enfileirado via ARQ — o evento já está salvo e visível
    (SSE já disparado antes desta task existir) antes desta task nem começar.
    """
    import os

    from vms.infrastructure.database import get_session_factory

    factory = get_session_factory()
    async with factory() as db:
        if not snapshot_path:
            return

        try:
            from vms.event_clips.service import build_event_clip_service

            await build_event_clip_service(db).generate_and_upload(
                vms_event_id=event_id, tenant_id=tenant_id, image_path=snapshot_path,
            )
        except Exception:
            logger.exception("Falha ao gerar clipe do evento %s (não crítico)", event_id)
            await db.rollback()

        try:
            from vms.notifications.service import build_notification_service

            image_bytes = None
            full_path = f"/snapshots/{snapshot_path}"
            if os.path.isfile(full_path):
                with open(full_path, "rb") as f:
                    image_bytes = f.read()
                bbox = (payload or {}).get("bbox")
                bbox_unit = (payload or {}).get("bbox_unit")
                if image_bytes and isinstance(bbox, list) and len(bbox) == 4:
                    image_bytes = _draw_bbox_overlay(image_bytes, bbox, bbox_unit)

            camera_name = None
            if camera_id:
                from sqlalchemy import select
                from vms.cameras.models import CameraModel

                camera_name = await db.scalar(
                    select(CameraModel.name).where(CameraModel.id == camera_id)
                )

            await build_notification_service(db).evaluate_and_dispatch(
                tenant_id=tenant_id,
                event_type=event_type,
                event_id=event_id,
                payload=payload or {},
                message=_build_friendly_message(event_type, payload or {}, camera_name),
                media_bytes=image_bytes,
                media_type="image",
                mime_type="image/jpeg",
            )
        except Exception:
            logger.exception("Falha ao notificar evento %s (não crítico)", event_id)
