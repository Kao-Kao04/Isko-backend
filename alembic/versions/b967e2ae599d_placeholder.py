"""placeholder for previously applied migration

Revision ID: b967e2ae599d
Revises: 52993517ee8a
Create Date: 2026-04-26 00:00:00.000000

This migration was applied to the database but the file was lost.
It is recreated as an empty placeholder to restore the migration chain.
"""
from typing import Sequence, Union

revision: str = 'b967e2ae599d'
down_revision: Union[str, None] = '52993517ee8a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
