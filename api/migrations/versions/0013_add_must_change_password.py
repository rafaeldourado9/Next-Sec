"""Adiciona users.must_change_password — força troca de senha no primeiro login.

Revision ID: 0013
Revises: 0012
Create Date: 2026-07-28 13:00:00.000000

NOTA (Next Sec): Sprint 7 — onboarding por licença (POST /admin/onboard-client)
cria o usuário gestor com uma senha padrão gerada pelo admin; essa coluna
marca que a senha ainda é a padrão e precisa ser trocada antes de liberar o
resto do app (ver ForcePasswordChangeGate.tsx no frontend e
PUT /auth/change-password no backend). Default false — usuários existentes
não são afetados.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("must_change_password", sa.Boolean(), nullable=False, server_default="false"),
    )


def downgrade() -> None:
    op.drop_column("users", "must_change_password")
