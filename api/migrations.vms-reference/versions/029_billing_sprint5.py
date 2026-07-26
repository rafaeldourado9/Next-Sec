"""Sprint 5: pricing_plans, tenant_billing_configs, usage_snapshots, invoices, payments; add deleted_at to tenants

Revision ID: 029
Revises: 028
Create Date: 2026-06-01 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "029"
down_revision: Union[str, None] = "028"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# UUID type que se adapta ao dialeto
_UUID = postgresql.UUID(as_uuid=False)
_JSON = postgresql.JSONB()


def upgrade() -> None:
    # deleted_at em tenants para soft delete
    op.add_column("tenants", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))

    # pricing_plans — created_by sem FK (campo auditoria, sem constraint hard)
    op.create_table(
        "pricing_plans",
        sa.Column("id", _UUID, primary_key=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("camera_price", sa.Numeric(10, 2), nullable=False, server_default="30.00"),
        sa.Column("storage_price_per_gb", sa.Numeric(10, 4), nullable=False, server_default="0.5000"),
        sa.Column("analytics_prices", _JSON, nullable=False, server_default="{}"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_by", _UUID, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_pricing_plans_active", "pricing_plans", ["is_active"])

    # tenant_billing_configs — FK para tenants e pricing_plans (ambos UUID)
    op.create_table(
        "tenant_billing_configs",
        sa.Column("id", _UUID, primary_key=True),
        sa.Column("tenant_id", _UUID, sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("pricing_plan_id", _UUID, sa.ForeignKey("pricing_plans.id", ondelete="SET NULL"), nullable=True),
        sa.Column("billing_cycle_day", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("custom_prices", _JSON, nullable=True),
        sa.Column("tax_rate", sa.Numeric(5, 4), nullable=False, server_default="0.0000"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", name="uq_billing_config_tenant"),
    )
    op.create_index("ix_tenant_billing_configs_tenant", "tenant_billing_configs", ["tenant_id"])

    # usage_snapshots
    op.create_table(
        "usage_snapshots",
        sa.Column("id", _UUID, primary_key=True),
        sa.Column("tenant_id", _UUID, sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("snapshot_date", sa.Date(), nullable=False),
        sa.Column("cameras_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("analytics_map", _JSON, nullable=False, server_default="{}"),
        sa.Column("storage_gb", sa.Numeric(12, 4), nullable=False, server_default="0.0000"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "snapshot_date", name="uq_usage_tenant_date"),
    )
    op.create_index("ix_usage_snapshots_tenant", "usage_snapshots", ["tenant_id"])

    # invoices
    op.create_table(
        "invoices",
        sa.Column("id", _UUID, primary_key=True),
        sa.Column("tenant_id", _UUID, sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("line_items", _JSON, nullable=False, server_default="[]"),
        sa.Column("subtotal", sa.Numeric(12, 2), nullable=False, server_default="0.00"),
        sa.Column("tax", sa.Numeric(12, 2), nullable=False, server_default="0.00"),
        sa.Column("total", sa.Numeric(12, 2), nullable=False, server_default="0.00"),
        sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
        sa.Column("generated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_invoices_tenant_status", "invoices", ["tenant_id", "status"])

    # payments — recorded_by sem FK (campo auditoria)
    op.create_table(
        "payments",
        sa.Column("id", _UUID, primary_key=True),
        sa.Column("invoice_id", _UUID, sa.ForeignKey("invoices.id", ondelete="CASCADE"), nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("method", sa.String(30), nullable=False, server_default="manual"),
        sa.Column("reference", sa.String(255), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("recorded_by", _UUID, nullable=True),
        sa.Column("recorded_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_payments_invoice", "payments", ["invoice_id"])


def downgrade() -> None:
    op.drop_index("ix_payments_invoice", "payments")
    op.drop_table("payments")
    op.drop_index("ix_invoices_tenant_status", "invoices")
    op.drop_table("invoices")
    op.drop_index("ix_usage_snapshots_tenant", "usage_snapshots")
    op.drop_table("usage_snapshots")
    op.drop_index("ix_tenant_billing_configs_tenant", "tenant_billing_configs")
    op.drop_table("tenant_billing_configs")
    op.drop_index("ix_pricing_plans_active", "pricing_plans")
    op.drop_table("pricing_plans")
    op.drop_column("tenants", "deleted_at")
