"""add allowance tracking to scholars

Revision ID: e4f5a6b7c8d9
Revises: f3g4h5i6j7k8
Create Date: 2026-05-15

"""
from alembic import op
import sqlalchemy as sa

revision = 'e4f5a6b7c8d9'
down_revision = 'f3g4h5i6j7k8'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('scholars', sa.Column('allowance_status', sa.String(), nullable=False, server_default='pending'))
    op.add_column('scholars', sa.Column('amount_released', sa.Integer(), nullable=True))
    op.add_column('scholars', sa.Column('last_release_date', sa.DateTime(timezone=True), nullable=True))
    op.add_column('scholars', sa.Column('next_release_date', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column('scholars', 'next_release_date')
    op.drop_column('scholars', 'last_release_date')
    op.drop_column('scholars', 'amount_released')
    op.drop_column('scholars', 'allowance_status')
