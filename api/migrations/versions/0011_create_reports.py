"""Cria a tabela reports — nunca foi migrada, apesar do model/feature existirem.

Revision ID: 0011
Revises: 0010
Create Date: 2026-07-27 19:00:00.000000

NOTA (Next Sec): achado ao investigar "relatórios não funcionam" — `GET/POST
/api/v1/reports` sempre retornava 500 (`UndefinedTableError: relation
"reports" does not exist"`). `ReportModel` (api/src/vms/reports/models.py)
existe e é usado ativamente por reports/router.py, service.py e pela task
`task_generate_report` (worker-low) desde que a feature foi implementada —
a migration que deveria ter criado a tabela nunca foi escrita. Reconstrói o
schema direto do model (colunas, índices), sem dado nenhum pra migrar já
que a tabela nunca existiu.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "reports",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("report_type", sa.String(50), nullable=False),
        sa.Column("parameters", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("status", sa.String(20), nullable=False, server_default=sa.text("'pending'")),
        sa.Column("file_path", sa.String(1000), nullable=True),
        sa.Column("sha256_hash", sa.String(64), nullable=True),
        sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=True),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=False), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_reports_tenant_created", "reports", ["tenant_id", "created_at"])
    op.create_index("ix_reports_status", "reports", ["status"])


def downgrade() -> None:
    op.drop_index("ix_reports_status", table_name="reports")
    op.drop_index("ix_reports_tenant_created", table_name="reports")
    op.drop_table("reports")
