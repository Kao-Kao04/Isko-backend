"""merge workflow redesign with auth flow

Revision ID: 6cce384e3e4c
Revises: b2c3d4e5f6a7, e1f2a3b4c5d6
Create Date: 2026-05-07 08:14:51.866623

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '6cce384e3e4c'
down_revision: Union[str, None] = ('b2c3d4e5f6a7', 'e1f2a3b4c5d6')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
