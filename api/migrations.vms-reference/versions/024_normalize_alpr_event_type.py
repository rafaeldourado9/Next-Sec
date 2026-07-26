"""normalize event_type 'alpr.detected' → 'alpr_detected'

Revision ID: 024
Revises: 023
Create Date: 2026-04-15 14:30:00.000000

O frontend filtra por 'alpr_detected' (underscore), mas o backend gravava
'alpr.detected' (dot). Padroniza para underscore — o canal SSE/bus continua
'alpr.detected', são namespaces independentes.
"""
from typing import Sequence, Union

from alembic import op

revision: str = '024'
down_revision: Union[str, Sequence[str], None] = '023'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "UPDATE vms_events SET event_type = 'alpr_detected' "
        "WHERE event_type = 'alpr.detected'"
    )


def downgrade() -> None:
    op.execute(
        "UPDATE vms_events SET event_type = 'alpr.detected' "
        "WHERE event_type = 'alpr_detected'"
    )
