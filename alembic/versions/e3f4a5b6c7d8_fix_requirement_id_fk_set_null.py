"""fix requirement_id FK to ON DELETE SET NULL so scholarship edits don't 500

Revision ID: e3f4a5b6c7d8
Revises: d2e3f4a5b6c7
Create Date: 2026-05-20 12:00:00.000000
"""
from typing import Sequence, Union
from alembic import op
from sqlalchemy import inspect

revision: str = 'e3f4a5b6c7d8'
down_revision: Union[str, None] = 'd2e3f4a5b6c7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _get_fk_name(bind, table: str, col: str) -> str | None:
    """Return the FK constraint name on table.col, or None if not found."""
    insp = inspect(bind)
    for fk in insp.get_foreign_keys(table):
        if col in fk['constrained_columns']:
            return fk.get('name')
    return None


def upgrade() -> None:
    bind = op.get_bind()
    fk_name = _get_fk_name(bind, 'application_documents', 'requirement_id')
    if fk_name:
        op.drop_constraint(fk_name, 'application_documents', type_='foreignkey')
    op.create_foreign_key(
        'application_documents_requirement_id_fkey',
        'application_documents', 'scholarship_requirements',
        ['requirement_id'], ['id'],
        ondelete='SET NULL',
    )


def downgrade() -> None:
    bind = op.get_bind()
    fk_name = _get_fk_name(bind, 'application_documents', 'requirement_id')
    if fk_name:
        op.drop_constraint(fk_name, 'application_documents', type_='foreignkey')
    op.create_foreign_key(
        'application_documents_requirement_id_fkey',
        'application_documents', 'scholarship_requirements',
        ['requirement_id'], ['id'],
    )
