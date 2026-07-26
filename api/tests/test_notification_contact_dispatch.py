"""Testes de NotificationService.evaluate_and_dispatch para destination_type=contact.

Ver .genesis/contracts/test-contracts.md — extensão de notification_rules.
"""
from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from vms.contacts.repository import ContactRepository
from vms.contacts.service import ContactService
from vms.iam.models import TenantModel
from vms.notifications import dispatcher as dispatcher_module
from vms.notifications.repository import NotificationLogRepository, NotificationRuleRepository
from vms.notifications.service import NotificationService


class FakeChannelAdapter:
    """Substitui o adapter real (Arcanum) — captura o que seria enviado."""

    def __init__(self, *, succeed: bool = True) -> None:
        self.sent: list[dict] = []
        self._succeed = succeed

    async def send(self, *, destination, message, media_url=None):
        self.sent.append({"destination": destination, "message": message, "media_url": media_url})
        return self._succeed, 200 if self._succeed else 500, "ok"


@pytest.fixture
def fake_adapter(monkeypatch: pytest.MonkeyPatch) -> FakeChannelAdapter:
    adapter = FakeChannelAdapter()
    monkeypatch.setattr(dispatcher_module, "build_channel_adapter", lambda channel, client=None: adapter)
    return adapter


def _svc(session: AsyncSession) -> NotificationService:
    return NotificationService(
        rule_repo=NotificationRuleRepository(session),
        log_repo=NotificationLogRepository(session),
        contact_repo=ContactRepository(session),
    )


async def _make_contact(session: AsyncSession, tenant: TenantModel) -> str:
    from vms.cameras.repository import CameraRepository
    contact_svc = ContactService(ContactRepository(session), CameraRepository(session))
    contact = await contact_svc.create_contact(
        tenant_id=tenant.id, phone_number="+5511999999999", name="Ana", camera_id=None,
    )
    return contact.id


class TestContactDispatch:
    async def test_matching_rule_sends_via_channel_adapter(
        self, db_session: AsyncSession, tenant_a: TenantModel, fake_adapter: FakeChannelAdapter
    ) -> None:
        contact_id = await _make_contact(db_session, tenant_a)
        svc = _svc(db_session)
        await svc.create_rule(
            tenant_id=tenant_a.id, name="Alerta intrusão", pattern="analytics.intrusion.*",
            destination_type="contact", contact_id=contact_id,
        )

        logs = await svc.evaluate_and_dispatch(
            tenant_id=tenant_a.id, event_type="analytics.intrusion.crossed",
            event_id="evt-1", payload={}, media_url="https://x.local/clip.mp4",
        )

        assert len(logs) == 1
        assert logs[0].status.value == "success"
        assert fake_adapter.sent[0]["destination"] == "+5511999999999"
        assert fake_adapter.sent[0]["media_url"] == "https://x.local/clip.mp4"

    async def test_non_matching_pattern_does_not_dispatch(
        self, db_session: AsyncSession, tenant_a: TenantModel, fake_adapter: FakeChannelAdapter
    ) -> None:
        contact_id = await _make_contact(db_session, tenant_a)
        svc = _svc(db_session)
        await svc.create_rule(
            tenant_id=tenant_a.id, name="Só face", pattern="analytics.face.*",
            destination_type="contact", contact_id=contact_id,
        )

        logs = await svc.evaluate_and_dispatch(
            tenant_id=tenant_a.id, event_type="analytics.intrusion.crossed",
            event_id="evt-2", payload={},
        )
        assert logs == []
        assert fake_adapter.sent == []

    async def test_inactive_contact_skips_dispatch(
        self, db_session: AsyncSession, tenant_a: TenantModel, fake_adapter: FakeChannelAdapter
    ) -> None:
        from vms.cameras.repository import CameraRepository
        contact_svc = ContactService(ContactRepository(db_session), CameraRepository(db_session))
        contact = await contact_svc.create_contact(
            tenant_id=tenant_a.id, phone_number="+5511999999999", name="Ana", camera_id=None,
        )
        await contact_svc.update_contact(contact.id, tenant_a.id, is_active=False)

        svc = _svc(db_session)
        await svc.create_rule(
            tenant_id=tenant_a.id, name="Alerta", pattern="*",
            destination_type="contact", contact_id=contact.id,
        )

        logs = await svc.evaluate_and_dispatch(
            tenant_id=tenant_a.id, event_type="analytics.intrusion.crossed",
            event_id="evt-3", payload={},
        )
        assert logs == []
        assert fake_adapter.sent == []

    async def test_create_rule_contact_without_contact_id_raises(
        self, db_session: AsyncSession, tenant_a: TenantModel
    ) -> None:
        svc = _svc(db_session)
        with pytest.raises(ValueError):
            await svc.create_rule(
                tenant_id=tenant_a.id, name="Inválida", pattern="*", destination_type="contact",
            )

    async def test_create_rule_webhook_without_url_raises(
        self, db_session: AsyncSession, tenant_a: TenantModel
    ) -> None:
        svc = _svc(db_session)
        with pytest.raises(ValueError):
            await svc.create_rule(
                tenant_id=tenant_a.id, name="Inválida", pattern="*", destination_type="webhook",
            )
