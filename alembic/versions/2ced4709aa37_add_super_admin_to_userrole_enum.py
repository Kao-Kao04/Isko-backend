"""add super_admin to userrole enum

Revision ID: 2ced4709aa37
Revises: fed13430eeea
Create Date: 2026-04-25 17:25:10.747100

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '2ced4709aa37'
down_revision: Union[str, None] = 'fed13430eeea'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ALTER TYPE cannot run inside a transaction in PostgreSQL
    op.execute("COMMIT")
    op.execute("ALTER TYPE userrole ADD VALUE IF NOT EXISTS 'super_admin'")


def downgrade() -> None:
    # PostgreSQL does not support removing enum values; a full type recreation is required
    pass
