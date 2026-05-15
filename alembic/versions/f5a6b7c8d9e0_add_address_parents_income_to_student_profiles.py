"""add address, parents, income to student_profiles

Revision ID: f5a6b7c8d9e0
Revises: e4f5a6b7c8d9
Create Date: 2026-05-15

"""
from alembic import op
import sqlalchemy as sa

revision = 'f5a6b7c8d9e0'
down_revision = 'e4f5a6b7c8d9'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('student_profiles', sa.Column('street_barangay',   sa.String(), nullable=True))
    op.add_column('student_profiles', sa.Column('city_municipality', sa.String(), nullable=True))
    op.add_column('student_profiles', sa.Column('province',          sa.String(), nullable=True))
    op.add_column('student_profiles', sa.Column('zip_code',          sa.String(), nullable=True))
    op.add_column('student_profiles', sa.Column('father_name',       sa.String(), nullable=True))
    op.add_column('student_profiles', sa.Column('father_occupation', sa.String(), nullable=True))
    op.add_column('student_profiles', sa.Column('mother_name',       sa.String(), nullable=True))
    op.add_column('student_profiles', sa.Column('mother_occupation', sa.String(), nullable=True))
    op.add_column('student_profiles', sa.Column('income_source',     sa.String(), nullable=True))
    op.add_column('student_profiles', sa.Column('monthly_income',    sa.String(), nullable=True))


def downgrade() -> None:
    for col in ['monthly_income', 'income_source', 'mother_occupation', 'mother_name',
                'father_occupation', 'father_name', 'zip_code', 'province',
                'city_municipality', 'street_barangay']:
        op.drop_column('student_profiles', col)
