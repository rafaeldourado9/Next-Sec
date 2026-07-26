"""branding: add white-label fields to tenants

Revision ID: 025
Revises: 024
Create Date: 2026-04-17 00:00:00.000000

Campos de identidade visual do integrador para uso nos PDFs de relatório.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '025'
down_revision: Union[str, None] = '024'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('tenants', sa.Column('company_name', sa.String(255), nullable=True))
    op.add_column('tenants', sa.Column('cnpj', sa.String(18), nullable=True))
    op.add_column('tenants', sa.Column('company_address', sa.String(500), nullable=True))
    op.add_column('tenants', sa.Column('logo_url', sa.String(1000), nullable=True))


def downgrade() -> None:
    op.drop_column('tenants', 'logo_url')
    op.drop_column('tenants', 'company_address')
    op.drop_column('tenants', 'cnpj')
    op.drop_column('tenants', 'company_name')
