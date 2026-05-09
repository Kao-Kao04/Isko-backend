"""cleanup account_status enum — remove stale pending default and orphan values

Revision ID: f1a2b3c4d5e6
Revises: 6cce384e3e4c
Create Date: 2026-05-07
"""
from typing import Sequence, Union
from alembic import op

revision: str = 'f1a2b3c4d5e6'
down_revision: Union[str, None] = '6cce384e3e4c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Safety: migrate any remaining 'pending' rows that escaped the previous migration
    op.execute("UPDATE users SET account_status = 'unregistered' WHERE account_status = 'pending'")

    # Change server default from stale 'pending' to correct 'unregistered'
    op.execute("ALTER TABLE users ALTER COLUMN account_status SET DEFAULT 'unregistered'")

    # Fix registration_documents.doc_type — add a CHECK constraint since we can't easily
    # change a VARCHAR to an ENUM without downtime, but we can enforce valid values
    op.execute("""
        ALTER TABLE registration_documents
        ADD CONSTRAINT chk_doc_type CHECK (doc_type IN ('school_id', 'cor'))
    """)


def downgrade() -> None:
    op.execute("ALTER TABLE registration_documents DROP CONSTRAINT IF EXISTS chk_doc_type")
    op.execute("ALTER TABLE users ALTER COLUMN account_status SET DEFAULT 'pending'")
