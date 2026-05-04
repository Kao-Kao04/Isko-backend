"""add account_status

Revision ID: 80e1944e59e6
Revises: 0133f2a23eaf
Create Date: 2026-04-22 20:16:16.977025

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '80e1944e59e6'
down_revision: Union[str, None] = '0133f2a23eaf'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    accountstatus = sa.Enum('pending', 'approved', 'rejected', name='accountstatus')
    accountstatus.create(op.get_bind(), checkfirst=True)
    op.add_column('users', sa.Column('account_status', accountstatus, nullable=False, server_default='pending'))


def downgrade() -> None:
    op.drop_column('users', 'account_status')
    sa.Enum(name='accountstatus').drop(op.get_bind(), checkfirst=True)
