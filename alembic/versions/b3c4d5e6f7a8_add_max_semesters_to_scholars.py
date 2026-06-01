"""add max_semesters to scholars

Revision ID: b3c4d5e6f7a8
Revises: a9b8c7d6e5f4, e078beeface3
Create Date: 2026-05-29

"""
from typing import Union
from alembic import op
import sqlalchemy as sa

revision: str = 'b3c4d5e6f7a8'
down_revision: Union[str, tuple] = ('a9b8c7d6e5f4', 'e078beeface3')
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('scholars', sa.Column('max_semesters', sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column('scholars', 'max_semesters')
