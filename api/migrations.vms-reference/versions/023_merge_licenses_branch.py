"""merge: junta branch órfão 016b (licenses legado) com linha principal

Revision ID: 023
Revises: 022, 016b
Create Date: 2026-04-14 00:00:00.000000

Resolve heads divergentes: `016b_create_licenses` era filho órfão de 015,
criado antes da consolidação em `022_license_keys`. Esta merge revision
fecha o branch sem efeito colateral.
"""
from typing import Sequence, Union

revision: str = '023'
down_revision: Union[str, Sequence[str], None] = ('022', '016b')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
