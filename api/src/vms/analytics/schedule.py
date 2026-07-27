"""Avaliação de janela de horário de ativação (ROISchedule).

Resolve a pergunta "esta zona está armada agora?" — usada pelo endpoint
`GET /plugins/rois` para que o serviço de analytics saiba, sem reimplementar
a lógica, se deve processar detecção para uma ROI no momento atual.
"""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from vms.analytics.models import ROISchedule

# NOTA (Next Sec): containers rodam em UTC, mas o horário cadastrado pelo
# usuário (input type="time" no ROIEditorPanel) é horário local do Brasil,
# sem nenhuma conversão. Comparar contra `datetime.now()` (UTC) deixava
# qualquer agendamento noturno armado ~3h fora do horário real (achado
# durante teste local — "eventos noturnos não funcionam"). Produto é
# Brasil-only (CNPJ, WhatsApp) — timezone fixo em vez de configurável por tenant.
_LOCAL_TZ = ZoneInfo("America/Sao_Paulo")


def _time_in_window(now_time, start, end) -> bool:  # noqa: ANN001
    """Verifica se `now_time` está dentro de [start, end), com suporte a
    janelas que cruzam a meia-noite (end < start, ex: 20:30-06:00)."""
    if start <= end:
        return start <= now_time < end
    return now_time >= start or now_time < end


def is_armed_now(schedules: list[ROISchedule], now: datetime | None = None) -> bool:
    """Retorna True se pelo menos um horário ativo cobre o instante `now`.

    Uma ROI sem nenhum horário cadastrado é considerada sempre armada —
    mantém o comportamento anterior (zona sem agendamento = sempre ativa),
    já que agendamento é uma feature opcional adicionada sobre o ROI já
    existente.
    """
    if not schedules:
        return True

    current = (now or datetime.now(_LOCAL_TZ)).astimezone(_LOCAL_TZ)
    current_time = current.time()
    current_dow = current.weekday()  # Monday=0 ... Sunday=6 (mesma convenção usada na API)

    for schedule in schedules:
        if not schedule.is_active:
            continue
        if schedule.day_of_week is not None and schedule.day_of_week != current_dow:
            continue
        if _time_in_window(current_time, schedule.start_time, schedule.end_time):
            return True

    return False
