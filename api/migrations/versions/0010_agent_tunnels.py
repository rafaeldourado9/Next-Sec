"""Cria agent_tunnels + sequence de alocação de IP do túnel WireGuard.

Revision ID: 0010
Revises: 0009
Create Date: 2026-07-27 16:30:00.000000

NOTA (Next Sec): túnel WireGuard pro "Criar Agente" (resolve CGNAT/ausência
de IP fixo do lado do cliente — ver docs/plans do túnel). Só guarda a chave
PÚBLICA do agente — a privada é gerada em memória na hora da criação e
devolvida uma única vez na resposta da API, nunca persistida (mesmo padrão
já usado por `api_keys`, que também não guarda a chave em texto puro).

A sequence começa em 2 porque .1 (dentro da subnet WG_SUBNET) é sempre o
próprio hub — cada agent recebe o próximo IP livre via `nextval()`, sem
precisar de lock manual/race condition em criação concorrente.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.execute("CREATE SEQUENCE agent_tunnel_ip_seq START WITH 2")

    op.create_table(
        "agent_tunnels",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("agent_id", postgresql.UUID(as_uuid=False),
                  sa.ForeignKey("agents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("public_key", sa.String(64), nullable=False),
        sa.Column("tunnel_ip", sa.String(18), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("agent_id", name="uq_agent_tunnels_agent"),
        sa.UniqueConstraint("tunnel_ip", name="uq_agent_tunnels_ip"),
    )
    op.create_index("idx_agent_tunnels_agent", "agent_tunnels", ["agent_id"])


def downgrade() -> None:
    op.drop_index("idx_agent_tunnels_agent", table_name="agent_tunnels")
    op.drop_table("agent_tunnels")
    op.execute("DROP SEQUENCE agent_tunnel_ip_seq")
