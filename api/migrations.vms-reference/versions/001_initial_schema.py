"""Criação do schema inicial — todas as tabelas do VMS.

Revision ID: 001
Revises:
Create Date: 2026-03-30 00:00:00.000000
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# Identificadores da revisão
revision: str = "001"
down_revision: str | None = None
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    """Cria todas as tabelas na ordem de dependência correta."""

    # 1. tenants
    op.create_table(
        "tenants",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("slug", sa.String(100), nullable=False, unique=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("facial_recognition_enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("facial_recognition_consent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_tenants_slug", "tenants", ["slug"], unique=True)

    # 2. users
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("hashed_password", sa.String(255), nullable=False),
        sa.Column("full_name", sa.String(255), nullable=False),
        sa.Column("role", sa.String(50), nullable=False, server_default="viewer"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_users_tenant_id", "users", ["tenant_id"])
    op.create_index("ix_users_email", "users", ["email"])

    # 3. api_keys
    op.create_table(
        "api_keys",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("owner_type", sa.String(50), nullable=False),
        sa.Column("owner_id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("key_hash", sa.String(255), nullable=False),
        sa.Column("prefix", sa.String(20), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_api_keys_tenant_id", "api_keys", ["tenant_id"])
    op.create_index("ix_api_keys_prefix", "api_keys", ["prefix"])

    # 4. agents
    op.create_table(
        "agents",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("status", sa.String(50), nullable=False, server_default="pending"),
        sa.Column("last_heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.String(50), nullable=True),
        sa.Column("streams_running", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("streams_failed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_agents_tenant_id", "agents", ["tenant_id"])

    # 5. cameras
    op.create_table(
        "cameras",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("agent_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("agents.id", ondelete="SET NULL"), nullable=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("location", sa.String(500), nullable=True),
        sa.Column("rtsp_url", sa.String(2000), nullable=False),
        sa.Column("manufacturer", sa.String(50), nullable=False, server_default="generic"),
        sa.Column("retention_days", sa.Integer(), nullable=False, server_default="7"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("is_online", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_cameras_tenant_id", "cameras", ["tenant_id"])
    op.create_index("ix_cameras_agent_id", "cameras", ["agent_id"])

    # 6. vms_events
    op.create_table(
        "vms_events",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("camera_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("cameras.id", ondelete="SET NULL"), nullable=True),
        sa.Column("event_type", sa.String(100), nullable=False),
        sa.Column("plate", sa.String(20), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_vms_events_tenant_id", "vms_events", ["tenant_id"])
    op.create_index("ix_vms_events_camera_id", "vms_events", ["camera_id"])
    op.create_index("ix_vms_events_event_type", "vms_events", ["event_type"])
    op.create_index("ix_vms_events_plate", "vms_events", ["plate"])
    op.create_index("ix_vms_events_tenant_occurred", "vms_events", ["tenant_id", "occurred_at"])

    # 7. recording_segments
    op.create_table(
        "recording_segments",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("camera_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("cameras.id", ondelete="CASCADE"), nullable=False),
        sa.Column("mediamtx_path", sa.String(500), nullable=False),
        sa.Column("file_path", sa.String(1000), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("duration_seconds", sa.Float(), nullable=False, server_default="0"),
        sa.Column("size_bytes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_recording_segments_tenant_id", "recording_segments", ["tenant_id"])
    op.create_index("ix_recording_segments_camera_id", "recording_segments", ["camera_id"])
    op.create_index("ix_recording_segments_started_at", "recording_segments", ["started_at"])
    op.create_index(
        "ix_recording_segments_tenant_camera_started",
        "recording_segments",
        ["tenant_id", "camera_id", "started_at"],
    )

    # 8. clips
    op.create_table(
        "clips",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("camera_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("cameras.id", ondelete="CASCADE"), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(50), nullable=False, server_default="pending"),
        sa.Column("file_path", sa.String(1000), nullable=True),
        sa.Column("vms_event_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("vms_events.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_clips_tenant_id", "clips", ["tenant_id"])
    op.create_index("ix_clips_camera_id", "clips", ["camera_id"])
    op.create_index("ix_clips_tenant_camera", "clips", ["tenant_id", "camera_id"])

    # 9. notification_rules
    op.create_table(
        "notification_rules",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("event_type_pattern", sa.String(200), nullable=False),
        sa.Column("destination_url", sa.String(2000), nullable=False),
        sa.Column("webhook_secret", sa.String(255), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_notification_rules_tenant_id", "notification_rules", ["tenant_id"])

    # 10. notification_logs
    op.create_table(
        "notification_logs",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("rule_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("notification_rules.id", ondelete="CASCADE"), nullable=False),
        sa.Column("vms_event_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("vms_events.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(50), nullable=False),
        sa.Column("response_code", sa.Integer(), nullable=True),
        sa.Column("response_body", sa.Text(), nullable=True),
        sa.Column("attempt", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("dispatched_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_notification_logs_tenant_id", "notification_logs", ["tenant_id"])
    op.create_index("ix_notification_logs_rule_id", "notification_logs", ["rule_id"])
    op.create_index("ix_notification_logs_vms_event_id", "notification_logs", ["vms_event_id"])

    # 11. regions_of_interest
    op.create_table(
        "regions_of_interest",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("camera_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("cameras.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("ia_type", sa.String(100), nullable=False),
        sa.Column("polygon_points", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("config", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_roi_tenant_id", "regions_of_interest", ["tenant_id"])
    op.create_index("ix_roi_camera_id", "regions_of_interest", ["camera_id"])
    op.create_index("ix_roi_tenant_camera", "regions_of_interest", ["tenant_id", "camera_id"])


def downgrade() -> None:
    """Remove todas as tabelas na ordem inversa (dependentes primeiro)."""
    op.drop_table("regions_of_interest")
    op.drop_table("notification_logs")
    op.drop_table("notification_rules")
    op.drop_table("clips")
    op.drop_table("recording_segments")
    op.drop_table("vms_events")
    op.drop_table("cameras")
    op.drop_table("agents")
    op.drop_table("api_keys")
    op.drop_table("users")
    op.drop_table("tenants")
