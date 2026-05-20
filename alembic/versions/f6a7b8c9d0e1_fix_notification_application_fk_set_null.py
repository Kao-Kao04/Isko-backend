"""fix notifications.application_id FK to ON DELETE SET NULL

Revision ID: f6a7b8c9d0e1
Revises: e3f4a5b6c7d8
Create Date: 2026-05-21 00:00:00.000000
"""
from typing import Sequence, Union
from alembic import op
from sqlalchemy import inspect

revision: str = 'f6a7b8c9d0e1'
down_revision: Union[str, None] = 'e3f4a5b6c7d8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _get_fk_name(bind, table: str, col: str) -> str | None:
    for fk in inspect(bind).get_foreign_keys(table):
        if col in fk['constrained_columns']:
            return fk.get('name')
    return None


def upgrade() -> None:
    bind = op.get_bind()
    fk_name = _get_fk_name(bind, 'notifications', 'application_id')
    if fk_name:
        op.drop_constraint(fk_name, 'notifications', type_='foreignkey')
    op.create_foreign_key(
        'notifications_application_id_fkey',
        'notifications', 'applications',
        ['application_id'], ['id'],
        ondelete='SET NULL',
    )


def downgrade() -> None:
    bind = op.get_bind()
    fk_name = _get_fk_name(bind, 'notifications', 'application_id')
    if fk_name:
        op.drop_constraint(fk_name, 'notifications', type_='foreignkey')
    op.create_foreign_key(
        'notifications_application_id_fkey',
        'notifications', 'applications',
        ['application_id'], ['id'],
    )
