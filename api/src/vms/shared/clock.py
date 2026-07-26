"""
Clock Abstraction — abstração de tempo para testabilidade.

Em vez de `datetime.utcnow()` espalhado pelo código, use `clock.now()`.
Em produção: RealClock (tempo real). Em testes: FakeClock (tempo fixo).

Uso:
    # Produção
    from vms.shared.clock import clock
    now = clock.now()

    # Testes
    from vms.shared.clock import FakeClock
    clock = FakeClock(datetime(2026, 4, 12, 10, 0, 0))
    now = clock.now()  # Sempre retorna o tempo fixo

Benefício: testes determinísticos, sem race conditions de tempo.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, timezone


class Clock(ABC):
    """Interface abstrata para provedor de tempo."""

    @abstractmethod
    def now(self) -> datetime:
        """Retorna o datetime atual (UTC)."""
        ...


class RealClock(Clock):
    """
    Clock real — usa o relógio do sistema.

    Este é o default em produção.
    """

    def now(self) -> datetime:
        return datetime.now(timezone.utc)


class FakeClock(Clock):
    """
    Clock falso — retorna tempo fixo.

    Use em testes para ter controle determinístico do tempo.

    Uso:
        fixed = datetime(2026, 4, 12, 10, 0, 0, tzinfo=timezone.utc)
        clock = FakeClock(fixed)

        # Avançar tempo manualmente
        clock.advance(hours=1)
    """

    def __init__(self, fixed_time: datetime) -> None:
        """
        Inicializa com tempo fixo.

        Args:
            fixed_time: datetime a ser retornado por now().
                        Deve ter timezone.utc para consistência.
        """
        if fixed_time.tzinfo is None:
            fixed_time = fixed_time.replace(tzinfo=timezone.utc)
        self._fixed_time = fixed_time

    def now(self) -> datetime:
        return self._fixed_time

    def advance(
        self,
        seconds: int = 0,
        minutes: int = 0,
        hours: int = 0,
        days: int = 0,
    ) -> None:
        """
        Avança o tempo fixo.

        Útil em testes para simular passagem de tempo.

        Uso:
            clock.advance(hours=1, minutes=30)
        """
        from datetime import timedelta

        delta = timedelta(
            days=days,
            hours=hours,
            minutes=minutes,
            seconds=seconds,
        )
        self._fixed_time = self._fixed_time + delta

    def set(self, new_time: datetime) -> None:
        """Define um novo tempo fixo."""
        if new_time.tzinfo is None:
            new_time = new_time.replace(tzinfo=timezone.utc)
        self._fixed_time = new_time


# Instância global (substituível em testes)
# Em produção: RealClock. Em testes, substitua por FakeClock.
clock: Clock = RealClock()
