"""add gwa request fields to student profiles

Revision ID: a1b2c3d4e5f6
Revises: fed13430eeea
Create Date: 2026-05-28 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = 'fed13430eeea'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('student_profiles', sa.Column('pending_gwa',            sa.String(),  nullable=True))
    op.add_column('student_profiles', sa.Column('gwa_proof_path',         sa.String(),  nullable=True))
    op.add_column('student_profiles', sa.Column('gwa_request_status',     sa.String(),  nullable=True))
    op.add_column('student_profiles', sa.Column('gwa_rejection_remarks',  sa.String(),  nullable=True))


def downgrade() -> None:
    op.drop_column('student_profiles', 'gwa_rejection_remarks')
    op.drop_column('student_profiles', 'gwa_request_status')
    op.drop_column('student_profiles', 'gwa_proof_path')
    op.drop_column('student_profiles', 'pending_gwa')
