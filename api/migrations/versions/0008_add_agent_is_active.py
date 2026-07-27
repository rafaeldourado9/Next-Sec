"""Adiciona agents.is_active — permite desativar um agent sem removê-lo.

Revision ID: 0008
Revises: 0007
Create Date: 2026-07-26 21:00:00.000000

NOTA (Next Sec): o frontend (AgentsPage.tsx) já chamava PUT /agents/{id} com
{is_active} para o botão "ativar/desativar", mas o backend não tinha rota
nem coluna para isso — resultava em 405 (achado durante teste local com
câmera/agent real). Agent desativado passa a ser rejeitado em heartbeat e
get_agent_config (ver AgentService).
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "agents",
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
    )


def downgrade() -> None:
    op.drop_column("agents", "is_active")
