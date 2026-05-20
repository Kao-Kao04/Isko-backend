"""add student_user_id, osfa_reply, replied_at to contact_inquiries

Revision ID: d2e3f4a5b6c7
Revises: c1d2e3f4a5b6
Create Date: 2026-05-19 23:00:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision: str = 'd2e3f4a5b6c7'
down_revision: Union[str, None] = 'c1d2e3f4a5b6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    cols = {c['name'] for c in inspect(bind).get_columns('contact_inquiries')}

    if 'student_user_id' not in cols:
        # Add column without inline ForeignKey — inline FK in add_column is
        # unreliable across Alembic/PostgreSQL versions; use create_foreign_key.
        op.add_column('contact_inquiries',
            sa.Column('student_user_id', sa.Integer(), nullable=True))
        op.create_foreign_key(
            'contact_inquiries_student_user_id_fkey',
            'contact_inquiries', 'users',
            ['student_user_id'], ['id'],
            ondelete='SET NULL',
        )

    if 'osfa_reply' not in cols:
        op.add_column('contact_inquiries',
            sa.Column('osfa_reply', sa.Text(), nullable=True))

    if 'replied_at' not in cols:
        op.add_column('contact_inquiries',
            sa.Column('replied_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_constraint('contact_inquiries_student_user_id_fkey',
                       'contact_inquiries', type_='foreignkey')
    op.drop_column('contact_inquiries', 'replied_at')
    op.drop_column('contact_inquiries', 'osfa_reply')
    op.drop_column('contact_inquiries', 'student_user_id')
