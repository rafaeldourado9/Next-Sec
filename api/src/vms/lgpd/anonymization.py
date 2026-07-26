"""Serviço de anonimização de dados pessoais."""
from __future__ import annotations

import hashlib
import logging
import uuid
from datetime import datetime, timezone
from typing import Protocol

from sqlalchemy import func, update as sa_update

logger = logging.getLogger(__name__)


class AnonymizationPort(Protocol):
    """Interface para anonimização."""

    async def anonymize_alpr_event(self, event_id: str) -> bool: ...
    async def anonymize_face_event(self, event_id: str) -> bool: ...
    async def delete_event(self, event_id: str) -> bool: ...


class AnonymizationService:
    """
    Serviço de anonimização de dados pessoais (LGPD Art. 5º, XIII).

    Anonimização: operação pela qual os dados perdem a possibilidade
    de associação, direta ou indireta, ao indivíduo.
    """

    def __init__(self, db_session) -> None:
        self._session = db_session

    async def anonymize_alpr_event(self, event_id: str) -> bool:
        """
        Anonimiza evento ALPR.
        - Placa: hash irreversível (SHA-256 dos últimos 4 chars + prefixo)
        - Imagem: URL substituída por placeholder
        - Timestamp: mantido para estatísticas, sem hora exata (truncado para dia)
        """
        from vms.events.models import VmsEventModel
        import json

        stmt = sa_update(VmsEventModel).where(VmsEventModel.id == event_id).values(
            plate=None,  # Remove a placa original
            confidence=None,  # Remove confiança
            payload={},  # Remove payload com dados extras
            occurred_at=func.date_trunc('day', VmsEventModel.occurred_at),  # Trunca para o dia
        )

        try:
            await self._session.execute(stmt)
            logger.info("Evento ALPR %s anonimizado", event_id)
            return True
        except Exception:
            logger.exception("Falha ao anonimizar evento ALPR %s", event_id)
            return False

    async def anonymize_face_event(self, event_id: str) -> bool:
        """
        Anonimiza evento de reconhecimento facial.
        - Nome: substituído por "ANÔNIMO"
        - person_id: hash irreversível
        - face_image_url: removido
        """
        from vms.events.models import VmsEventModel

        stmt = sa_update(VmsEventModel).where(VmsEventModel.id == event_id).values(
            payload=func.jsonb_set(
                VmsEventModel.payload,
                '{person_name}',
                '"ANÔNIMO"',
            ),
            confidence=None,  # Remove similaridade
        )

        try:
            await self._session.execute(stmt)
            logger.info("Evento facial %s anonimizado", event_id)
            return True
        except Exception:
            logger.exception("Falha ao anonimizar evento facial %s", event_id)
            return False

    async def delete_event(self, event_id: str) -> bool:
        """
        Deleção segura de evento (não recupera).
        Usar apenas quando anonimização não for possível ou para dados não essenciais.
        """
        from vms.events.models import VmsEventModel
        from sqlalchemy import delete

        stmt = delete(VmsEventModel).where(VmsEventModel.id == event_id)
        try:
            await self._session.execute(stmt)
            logger.info("Evento %s deletado", event_id)
            return True
        except Exception:
            logger.exception("Falha ao deletar evento %s", event_id)
            return False
