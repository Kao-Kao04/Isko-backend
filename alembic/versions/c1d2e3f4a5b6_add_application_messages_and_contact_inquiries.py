"""add application_messages and contact_inquiries tables

Revision ID: c1d2e3f4a5b6
Revises: d4b7e5162f49
Create Date: 2026-05-17 12:00:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision: str = 'c1d2e3f4a5b6'
down_revision: Union[str, None] = 'd4b7e5162f49'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    existing = inspect(bind).get_table_names()

    if 'application_messages' not in existing:
        op.create_table(
            'application_messages',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('application_id', sa.Integer(), sa.ForeignKey('applications.id', ondelete='CASCADE'), nullable=False),
            sa.Column('sender_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
            sa.Column('body', sa.Text(), nullable=False),
            sa.Column('is_read', sa.Boolean(), nullable=False, server_default='false'),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.PrimaryKeyConstraint('id'),
        )
        op.create_index('ix_application_messages_application_id', 'application_messages', ['application_id'])

    if 'contact_inquiries' not in existing:
        op.create_table(
            'contact_inquiries',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('name', sa.String(), nullable=False),
            sa.Column('email', sa.String(), nullable=False),
            sa.Column('subject', sa.String(), nullable=True),
            sa.Column('message', sa.Text(), nullable=False),
            sa.Column('is_read', sa.Boolean(), nullable=False, server_default='false'),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.PrimaryKeyConstraint('id'),
        )


def downgrade() -> None:
    op.drop_table('contact_inquiries')
    op.drop_index('ix_application_messages_application_id', table_name='application_messages')
    op.drop_table('application_messages')
