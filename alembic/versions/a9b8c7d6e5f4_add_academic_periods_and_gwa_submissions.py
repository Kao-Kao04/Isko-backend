"""add academic_periods and gwa_submissions tables

Revision ID: a9b8c7d6e5f4
Revises: d4b7e5162f49
Create Date: 2026-05-29
"""
from typing import Sequence, Union
import sqlalchemy as sa
from alembic import op

revision: str = 'a9b8c7d6e5f4'
down_revision: Union[str, None] = 'd4b7e5162f49'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'academic_periods',
        sa.Column('id',                 sa.Integer(),     nullable=False),
        sa.Column('academic_year',      sa.String(),      nullable=False),
        sa.Column('semester',           sa.Enum('first', 'second', 'summer', name='semestertype'), nullable=False),
        sa.Column('start_date',         sa.Date(),        nullable=False),
        sa.Column('end_date',           sa.Date(),        nullable=False),
        sa.Column('counts_toward_max',  sa.Boolean(),     nullable=False, server_default='true'),
        sa.Column('created_at',         sa.DateTime(timezone=True), server_default=sa.text('now()')),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('academic_year', 'semester', name='uq_period_year_sem'),
    )
    op.create_index('ix_academic_periods_id', 'academic_periods', ['id'])

    op.create_table(
        'gwa_submissions',
        sa.Column('id',                  sa.Integer(),    nullable=False),
        sa.Column('scholar_id',          sa.Integer(),    nullable=False),
        sa.Column('period_id',           sa.Integer(),    nullable=False),
        sa.Column('declared_gwa',        sa.String(),     nullable=True),
        sa.Column('proof_path',          sa.String(),     nullable=False),
        sa.Column('has_grade_below_2_5', sa.Boolean(),    nullable=False, server_default='false'),
        sa.Column('status',              sa.Enum('pending', 'approved', 'rejected', name='gwasubmissionstatus'), nullable=False, server_default='pending'),
        sa.Column('rejection_remarks',   sa.Text(),       nullable=True),
        sa.Column('submitted_at',        sa.DateTime(timezone=True), server_default=sa.text('now()')),
        sa.Column('reviewed_at',         sa.DateTime(timezone=True), nullable=True),
        sa.Column('reviewed_by_id',      sa.Integer(),    nullable=True),
        sa.ForeignKeyConstraint(['scholar_id'],    ['scholars.id'],   ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['period_id'],     ['academic_periods.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['reviewed_by_id'], ['users.id'],    ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('scholar_id', 'period_id', name='uq_gwa_sub_scholar_period'),
    )
    op.create_index('ix_gwa_submissions_id',        'gwa_submissions', ['id'])
    op.create_index('ix_gwa_submissions_scholar_id', 'gwa_submissions', ['scholar_id'])


def downgrade() -> None:
    op.drop_index('ix_gwa_submissions_scholar_id', 'gwa_submissions')
    op.drop_index('ix_gwa_submissions_id',         'gwa_submissions')
    op.drop_table('gwa_submissions')
    op.drop_index('ix_academic_periods_id', 'academic_periods')
    op.drop_table('academic_periods')
    op.execute("DROP TYPE IF EXISTS gwasubmissionstatus")
    op.execute("DROP TYPE IF EXISTS semestertype")
