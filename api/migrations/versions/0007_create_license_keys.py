"""Cria license_keys — versão mínima do billing só para o LicenseGate/onboarding.

Revision ID: 0007
Revises: 0006
Create Date: 2026-07-26 16:45:00.000000

NOTA (Next Sec): não reintroduz GMV/faturas/planos/analytics_pricing do vms/
original — isso segue fora do escopo do MVP (ver .genesis/architecture/
reuse-plan.md). `tenants.license_key_id`/`onboarding_complete` já existem
desde 0001_baseline_schema; faltava só a tabela que o valor referencia.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "license_keys",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("license_key", sa.String(29), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=False), nullable=True),
        sa.Column("deployment_model", sa.String(20), nullable=False, server_default="self_hosted"),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("max_cameras", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("license_key", name="uq_license_keys_key"),
    )
    op.create_index("idx_license_keys_tenant", "license_keys", ["tenant_id"])


def downgrade() -> None:
    op.drop_index("idx_license_keys_tenant", table_name="license_keys")
    op.drop_table("license_keys")
