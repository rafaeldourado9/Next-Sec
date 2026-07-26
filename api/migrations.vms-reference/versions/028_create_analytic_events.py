"""create analytic_events table with pgvector extension

Revision ID: 028
Revises: 027
Create Date: 2026-05-31 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "028"
down_revision: Union[str, None] = "027"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # pgvector extension — requer instalação no PostgreSQL host.
    # No MVP usamos JSONB para embedding (compatível com SQLite de testes).
    # op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "analytic_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "camera_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("cameras.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("event_type", sa.String(50), nullable=False),
        sa.Column("attributes", postgresql.JSONB, nullable=True),
        sa.Column(
            "embedding", postgresql.JSONB, nullable=True
        ),  # vetor 512-dim como JSONB para compat SQLite
        sa.Column("thumbnail_key", sa.String(500), nullable=True),
        sa.Column("segment_key", sa.String(500), nullable=True),
        sa.Column("confidence", sa.Float, nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # Índices obrigatórios
    op.create_index(
        "ix_ae_tenant_camera_occurred", "analytic_events", ["tenant_id", "camera_id", "occurred_at"]
    )
    op.create_index("ix_ae_event_type_occurred", "analytic_events", ["event_type", "occurred_at"])
    op.create_index(
        "ix_ae_attributes_gin", "analytic_events", ["attributes"], postgresql_using="gin"
    )


def downgrade() -> None:
    op.drop_index("ix_ae_attributes_gin", table_name="analytic_events")
    op.drop_index("ix_ae_event_type_occurred", table_name="analytic_events")
    op.drop_index("ix_ae_tenant_camera_occurred", table_name="analytic_events")
    op.drop_table("analytic_events")
