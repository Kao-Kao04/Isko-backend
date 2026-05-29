"""merge_heads

Revision ID: e078beeface3
Revises: b967e2ae599d, f6a7b8c9d0e1
Create Date: 2026-05-29 19:25:55.673088

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e078beeface3'
down_revision: Union[str, None] = ('b967e2ae599d', 'f6a7b8c9d0e1')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
