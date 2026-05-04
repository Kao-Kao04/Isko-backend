"""add department to users category to scholarships

Revision ID: fed13430eeea
Revises: 953081a9bbc4
Create Date: 2026-04-25 17:15:29.125643

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'fed13430eeea'
down_revision: Union[str, None] = '953081a9bbc4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    categoryenum = sa.Enum('public', 'private', name='categoryenum')
    categoryenum.create(op.get_bind(), checkfirst=True)
    departmentenum = sa.Enum('public', 'private', name='departmentenum')
    departmentenum.create(op.get_bind(), checkfirst=True)

    op.add_column('scholarships', sa.Column('category', sa.Enum('public', 'private', name='categoryenum', create_constraint=True), nullable=True))
    op.add_column('users', sa.Column('department', sa.Enum('public', 'private', name='departmentenum', create_constraint=True), nullable=True))


def downgrade() -> None:
    op.drop_column('users', 'department')
    op.drop_column('scholarships', 'category')
    op.execute('DROP TYPE IF EXISTS departmentenum')
    op.execute('DROP TYPE IF EXISTS categoryenum')
