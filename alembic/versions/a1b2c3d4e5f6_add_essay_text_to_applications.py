"""add essay_text to applications

Revision ID: a1b2c3d4e5f6
Revises: fed13430eeea
Create Date: 2026-05-26 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = 'fed13430eeea'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('applications', sa.Column('essay_text', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('applications', 'essay_text')
