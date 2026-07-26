"""Testes de roi_schedules — ver .genesis/contracts/test-contracts.md.

Foco na lógica de `is_armed_now` (a parte de maior risco: janela de horário
que cruza a meia-noite) e no roundtrip de persistência via SQLAlchemy.
"""
from __future__ import annotations

from datetime import datetime, time

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from vms.analytics.models import AnalyticsROI, ROISchedule
from vms.analytics.schedule import is_armed_now
from vms.iam.models import TenantModel


def _schedule(
    *, start: time, end: time, day_of_week: int | None = None, is_active: bool = True
) -> ROISchedule:
    return ROISchedule(
        id="s1", roi_id="roi1", day_of_week=day_of_week,
        start_time=start, end_time=end, is_active=is_active,
    )


class TestIsArmedNow:
    def test_no_schedules_means_always_armed(self) -> None:
        assert is_armed_now([]) is True

    def test_within_same_day_window(self) -> None:
        sched = _schedule(start=time(8, 0), end=time(18, 0))
        assert is_armed_now([sched], now=datetime(2026, 7, 26, 12, 0)) is True
        assert is_armed_now([sched], now=datetime(2026, 7, 26, 19, 0)) is False

    def test_midnight_crossing_window_at_21h(self) -> None:
        """20:30-06:00 — 21h deve estar armado."""
        sched = _schedule(start=time(20, 30), end=time(6, 0))
        assert is_armed_now([sched], now=datetime(2026, 7, 26, 21, 0)) is True

    def test_midnight_crossing_window_at_05h(self) -> None:
        """20:30-06:00 — 05h (depois da virada) deve estar armado."""
        sched = _schedule(start=time(20, 30), end=time(6, 0))
        assert is_armed_now([sched], now=datetime(2026, 7, 27, 5, 0)) is True

    def test_midnight_crossing_window_at_10h_is_not_armed(self) -> None:
        """20:30-06:00 — 10h da manhã não deve estar armado."""
        sched = _schedule(start=time(20, 30), end=time(6, 0))
        assert is_armed_now([sched], now=datetime(2026, 7, 27, 10, 0)) is False

    def test_day_of_week_filter(self) -> None:
        # 2026-07-26 é domingo (weekday()==6)
        sunday = datetime(2026, 7, 26, 21, 0)
        monday = datetime(2026, 7, 27, 21, 0)
        sched_monday_only = _schedule(start=time(20, 0), end=time(23, 0), day_of_week=0)
        assert is_armed_now([sched_monday_only], now=sunday) is False
        assert is_armed_now([sched_monday_only], now=monday) is True

    def test_multiple_shifts_same_day(self) -> None:
        """Dois turnos no mesmo dia (ex: intervalo de almoço + noite)."""
        lunch = _schedule(start=time(12, 0), end=time(13, 0))
        night = _schedule(start=time(20, 0), end=time(23, 59))
        schedules = [lunch, night]
        assert is_armed_now(schedules, now=datetime(2026, 7, 26, 12, 30)) is True
        assert is_armed_now(schedules, now=datetime(2026, 7, 26, 21, 0)) is True
        assert is_armed_now(schedules, now=datetime(2026, 7, 26, 16, 0)) is False

    def test_inactive_schedule_is_ignored(self) -> None:
        sched = _schedule(start=time(0, 0), end=time(23, 59), is_active=False)
        assert is_armed_now([sched], now=datetime(2026, 7, 26, 12, 0)) is False


@pytest.mark.asyncio
class TestROISchedulePersistence:
    async def test_create_schedule_for_roi(
        self, db_session: AsyncSession, tenant_a: TenantModel
    ) -> None:
        roi = AnalyticsROI(
            tenant_id=tenant_a.id,
            camera_id="cam-1",
            plugin_id="intrusion",
            name="Entrada",
            polygon=[[0.1, 0.1], [0.9, 0.1], [0.9, 0.9], [0.1, 0.9]],
        )
        db_session.add(roi)
        await db_session.flush()

        schedule = ROISchedule(
            roi_id=roi.id, day_of_week=None, start_time=time(20, 30), end_time=time(6, 0),
        )
        db_session.add(schedule)
        await db_session.flush()
        await db_session.refresh(schedule)

        assert schedule.roi_id == roi.id
        assert schedule.is_active is True

    async def test_multiple_schedules_per_roi(
        self, db_session: AsyncSession, tenant_a: TenantModel
    ) -> None:
        roi = AnalyticsROI(
            tenant_id=tenant_a.id, camera_id="cam-1", plugin_id="intrusion", name="Entrada",
            polygon=[[0.1, 0.1], [0.9, 0.1], [0.9, 0.9], [0.1, 0.9]],
        )
        db_session.add(roi)
        await db_session.flush()

        db_session.add(ROISchedule(roi_id=roi.id, start_time=time(8, 0), end_time=time(12, 0)))
        db_session.add(ROISchedule(roi_id=roi.id, start_time=time(20, 0), end_time=time(23, 0)))
        await db_session.flush()

        from sqlalchemy import select
        result = await db_session.execute(
            select(ROISchedule).where(ROISchedule.roi_id == roi.id)
        )
        schedules = result.scalars().all()
        assert len(schedules) == 2
