"""add_link_to_notifications

Revision ID: d4b7e5162f49
Revises: f5a6b7c8d9e0
Create Date: 2026-05-16 12:55:59.745637

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'd4b7e5162f49'
down_revision: Union[str, None] = 'f5a6b7c8d9e0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('notifications', sa.Column('link', sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column('notifications', 'link')
