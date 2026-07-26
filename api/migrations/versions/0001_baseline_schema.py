"""Baseline schema — Next Sec (schema herdado do vms/, sem recordings/vod/streaming/billing).

Revision ID: 0001
Revises:
Create Date: 2026-07-26 00:00:00.000000

Ver .genesis/contracts/db-schema.sql (fonte da verdade) e
.genesis/contracts/migrations.md (decisão de não reaproveitar o histórico
de migrations do vms/ — banco novo e vazio).
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.execute('CREATE EXTENSION IF NOT EXISTS "pgcrypto"')

    # ─── tenants ────────────────────────────────────────────────────────────
    op.create_table(
        "tenants",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("slug", sa.String(100), nullable=False, unique=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("facial_recognition_enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("facial_recognition_consent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("license_key_id", postgresql.UUID(as_uuid=False), nullable=True),
        sa.Column("onboarding_complete", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("company_name", sa.String(255), nullable=True),
        sa.Column("cnpj", sa.String(18), nullable=True),
        sa.Column("company_address", sa.String(500), nullable=True),
        sa.Column("logo_url", sa.String(1000), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("idx_tenants_is_active", "tenants", ["is_active"],
                     postgresql_where=sa.text("deleted_at IS NULL"))

    # ─── users ──────────────────────────────────────────────────────────────
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=False),
                  sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("hashed_password", sa.String(255), nullable=False),
        sa.Column("full_name", sa.String(255), nullable=False),
        sa.Column("role", sa.String(50), nullable=False, server_default="viewer"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("tenant_id", "email", name="uq_users_tenant_email"),
    )
    op.create_index("idx_users_tenant", "users", ["tenant_id"])
    op.create_index("idx_users_email", "users", ["email"])

    # ─── api_keys ───────────────────────────────────────────────────────────
    op.create_table(
        "api_keys",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=False),
                  sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("owner_type", sa.String(50), nullable=False),
        sa.Column("owner_id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("key_hash", sa.String(255), nullable=False),
        sa.Column("prefix", sa.String(20), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("idx_api_keys_tenant", "api_keys", ["tenant_id"])
    op.create_index("idx_api_keys_prefix", "api_keys", ["prefix"])

    # ─── agents ─────────────────────────────────────────────────────────────
    op.create_table(
        "agents",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=False),
                  sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("status", sa.String(50), nullable=False, server_default="pending"),
        sa.Column("last_heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.String(50), nullable=True),
        sa.Column("streams_running", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("streams_failed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("idx_agents_tenant", "agents", ["tenant_id"])

    # ─── cameras ────────────────────────────────────────────────────────────
    op.create_table(
        "cameras",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=False),
                  sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("agent_id", postgresql.UUID(as_uuid=False),
                  sa.ForeignKey("agents.id", ondelete="SET NULL"), nullable=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("location", sa.String(500), nullable=True),
        sa.Column("address", sa.String(500), nullable=True),
        sa.Column("latitude", sa.Float(), nullable=True),
        sa.Column("longitude", sa.Float(), nullable=True),
        sa.Column("ia_enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("stream_protocol", sa.String(50), nullable=False, server_default="rtsp_pull"),
        sa.Column("rtsp_url", sa.String(2000), nullable=True),
        sa.Column("rtmp_stream_key", sa.String(100), nullable=True, unique=True),
        sa.Column("onvif_url", sa.String(2000), nullable=True),
        sa.Column("onvif_username", sa.String(255), nullable=True),
        sa.Column("onvif_password", sa.String(500), nullable=True),
        sa.Column("manufacturer", sa.String(50), nullable=False, server_default="generic"),
        sa.Column("camera_type", sa.String(50), nullable=False, server_default="internal"),
        sa.Column("retention_days", sa.Integer(), nullable=False, server_default="7"),
        sa.Column("stream_quality", sa.String(20), nullable=False, server_default="high"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("is_online", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("ptz_supported", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("isapi_enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("isapi_base_url", sa.String(2000), nullable=True),
        sa.Column("isapi_username", sa.String(255), nullable=True),
        sa.Column("isapi_password", sa.String(500), nullable=True),
        sa.Column("serial_number", sa.String(100), nullable=True),
        sa.Column("firmware_version", sa.String(50), nullable=True),
        sa.Column("model_name", sa.String(200), nullable=True),
        sa.Column("isapi_capabilities", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("idx_cameras_tenant", "cameras", ["tenant_id"])
    op.create_index("idx_cameras_agent", "cameras", ["agent_id"])
    op.create_index("idx_cameras_active", "cameras", ["tenant_id", "is_active"],
                     postgresql_where=sa.text("is_active = true"))

    # ─── analytics_rois ─────────────────────────────────────────────────────
    op.create_table(
        "analytics_rois",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=False),
                  sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("camera_id", sa.String(100), nullable=False),
        sa.Column("plugin_id", sa.String(50), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("polygon", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("config", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("idx_analytics_rois_tenant", "analytics_rois", ["tenant_id"])
    op.create_index("idx_analytics_rois_camera", "analytics_rois", ["camera_id"])
    op.create_index("idx_analytics_rois_plugin", "analytics_rois", ["plugin_id"])

    # ─── plugin_installations ───────────────────────────────────────────────
    op.create_table(
        "plugin_installations",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("plugin_id", sa.String(50), nullable=False),
        sa.Column("plugin_name", sa.String(100), nullable=False),
        sa.Column("version", sa.String(20), nullable=False, server_default="1.0.0"),
        sa.Column("edge_agent_id", sa.String(100), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=False),
                  sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="installed"),
        sa.Column("settings", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("model_path", sa.String(500), nullable=True),
        sa.Column("fps_target", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("idx_plugin_installations_tenant", "plugin_installations", ["tenant_id"])
    op.create_index("idx_plugin_installations_agent", "plugin_installations", ["edge_agent_id"])
    op.create_index("idx_plugin_installations_status", "plugin_installations", ["status"])

    # ─── analytics_events ───────────────────────────────────────────────────
    op.create_table(
        "analytics_events",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("plugin_installation_id", postgresql.UUID(as_uuid=False),
                  sa.ForeignKey("plugin_installations.id", ondelete="SET NULL"), nullable=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=False),
                  sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("camera_id", sa.String(100), nullable=False),
        sa.Column("camera_name", sa.String(200), nullable=True),
        sa.Column("plugin_id", sa.String(50), nullable=False),
        sa.Column("event_type", sa.String(100), nullable=False),
        sa.Column("severity", sa.String(20), nullable=False, server_default="info"),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("payload", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("snapshot_path", sa.String(500), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("idx_analytics_events_tenant", "analytics_events", ["tenant_id"])
    op.create_index("idx_analytics_events_camera", "analytics_events", ["camera_id"])
    op.create_index("idx_analytics_events_plugin", "analytics_events", ["plugin_id"])
    op.create_index("idx_analytics_events_severity", "analytics_events", ["severity"])
    op.create_index("idx_analytics_events_occurred", "analytics_events", ["occurred_at"])
    op.create_index("idx_analytics_events_tenant_time", "analytics_events", ["tenant_id", "occurred_at"])

    # ─── vms_events ─────────────────────────────────────────────────────────
    op.create_table(
        "vms_events",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=False),
                  sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("camera_id", postgresql.UUID(as_uuid=False),
                  sa.ForeignKey("cameras.id", ondelete="SET NULL"), nullable=True),
        sa.Column("event_type", sa.String(100), nullable=False),
        sa.Column("plate", sa.String(20), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("image_path", sa.String(500), nullable=True),
        sa.Column("payload", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("idx_vms_events_tenant", "vms_events", ["tenant_id"])
    op.create_index("idx_vms_events_camera", "vms_events", ["camera_id"])
    op.create_index("idx_vms_events_type", "vms_events", ["event_type"])
    op.create_index("idx_vms_events_tenant_occurred", "vms_events", ["tenant_id", "occurred_at"])
    op.create_index("idx_vms_events_plate", "vms_events", ["plate"])

    # ─── notification_rules ─────────────────────────────────────────────────
    op.create_table(
        "notification_rules",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=False),
                  sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("event_type_pattern", sa.String(200), nullable=False),
        sa.Column("destination_url", sa.String(2000), nullable=False),
        sa.Column("webhook_secret", sa.String(255), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("idx_notification_rules_tenant", "notification_rules", ["tenant_id"])

    # ─── notification_logs ──────────────────────────────────────────────────
    op.create_table(
        "notification_logs",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=False),
                  sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("rule_id", postgresql.UUID(as_uuid=False),
                  sa.ForeignKey("notification_rules.id", ondelete="CASCADE"), nullable=False),
        sa.Column("vms_event_id", postgresql.UUID(as_uuid=False),
                  sa.ForeignKey("vms_events.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(50), nullable=False),
        sa.Column("response_code", sa.Integer(), nullable=True),
        sa.Column("response_body", sa.Text(), nullable=True),
        sa.Column("attempt", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("dispatched_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("idx_notification_logs_tenant", "notification_logs", ["tenant_id"])
    op.create_index("idx_notification_logs_rule", "notification_logs", ["rule_id"])
    op.create_index("idx_notification_logs_event", "notification_logs", ["vms_event_id"])

    # ─── retention_policies (LGPD) ──────────────────────────────────────────
    op.create_table(
        "retention_policies",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=False),
                  sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("data_type", sa.String(50), nullable=False),
        sa.Column("retention_days", sa.Integer(), nullable=False),
        sa.Column("anonymize_instead_of_delete", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("auto_enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("tenant_id", "data_type", name="uq_retention_policy"),
    )

    # ─── consent_records (LGPD, append-only) ────────────────────────────────
    op.create_table(
        "consent_records",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=False),
                  sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=False), nullable=True),
        sa.Column("data_type", sa.String(50), nullable=False),
        sa.Column("action", sa.String(20), nullable=False),
        sa.Column("consent_text_hash", sa.String(64), nullable=True),
        sa.Column("ip_address", sa.String(45), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("idx_consent_records_tenant", "consent_records", ["tenant_id"])
    op.create_index("idx_consent_records_type", "consent_records", ["tenant_id", "data_type"])

    # ─── audit_log (append-only — nunca UPDATE/DELETE) ──────────────────────
    op.create_table(
        "audit_log",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=False), nullable=True),
        sa.Column("user_email", sa.String(255), nullable=True),
        sa.Column("user_role", sa.String(50), nullable=True),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("resource_type", sa.String(50), nullable=True),
        sa.Column("resource_id", postgresql.UUID(as_uuid=False), nullable=True),
        sa.Column("resource_name", sa.String(255), nullable=True),
        sa.Column("ip_address", sa.String(45), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("request_id", postgresql.UUID(as_uuid=False), nullable=True),
        sa.Column("payload", postgresql.JSONB(), nullable=True, server_default="{}"),
        sa.Column("result", sa.String(20), nullable=True, server_default="success"),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("idx_audit_log_tenant_occurred", "audit_log", ["tenant_id", "occurred_at"])
    op.create_index("idx_audit_log_user_occurred", "audit_log", ["user_id", "occurred_at"])
    op.create_index("idx_audit_log_action_occurred", "audit_log", ["action", "occurred_at"])
    op.create_index("idx_audit_log_resource", "audit_log", ["resource_type", "resource_id"])


def downgrade() -> None:
    op.drop_table("audit_log")
    op.drop_table("consent_records")
    op.drop_table("retention_policies")
    op.drop_table("notification_logs")
    op.drop_table("notification_rules")
    op.drop_table("vms_events")
    op.drop_table("analytics_events")
    op.drop_table("plugin_installations")
    op.drop_table("analytics_rois")
    op.drop_table("cameras")
    op.drop_table("agents")
    op.drop_table("api_keys")
    op.drop_table("users")
    op.drop_table("tenants")
