"""auth flow v2 — new AccountStatus values, rejection_remarks, registration_documents

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-04-27 00:01:00.000000

All statements use IF NOT EXISTS / ADD VALUE IF NOT EXISTS so this migration
is safe to run even if b967e2ae599d already applied these changes.
"""
from typing import Sequence, Union
from alembic import op

revision: str = 'b2c3d4e5f6a7'
down_revision: Union[str, None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add new enum values — safe to re-run
    op.execute("ALTER TYPE accountstatus ADD VALUE IF NOT EXISTS 'unregistered'")
    op.execute("ALTER TYPE accountstatus ADD VALUE IF NOT EXISTS 'pending_verification'")
    op.execute("ALTER TYPE accountstatus ADD VALUE IF NOT EXISTS 'verified'")

    # Migrate existing data (idempotent — same rows just get the same value)
    op.execute("UPDATE users SET account_status = 'unregistered' WHERE account_status = 'pending'")
    op.execute("UPDATE users SET account_status = 'verified' WHERE account_status = 'approved' AND role = 'student'")

    # Add rejection_remarks column if it doesn't already exist
    op.execute("""
        ALTER TABLE users
        ADD COLUMN IF NOT EXISTS rejection_remarks VARCHAR
    """)

    # Create registration_documents table if it doesn't already exist
    op.execute("""
        CREATE TABLE IF NOT EXISTS registration_documents (
            id               SERIAL PRIMARY KEY,
            user_id          INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            doc_type         VARCHAR NOT NULL,
            filename         VARCHAR NOT NULL,
            storage_path     VARCHAR NOT NULL,
            content_type     VARCHAR NOT NULL,
            uploaded_at      TIMESTAMPTZ DEFAULT NOW()
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_registration_documents_user_id
        ON registration_documents (user_id)
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_registration_documents_user_id")
    op.execute("DROP TABLE IF EXISTS registration_documents")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS rejection_remarks")
    # Note: cannot remove enum values in PostgreSQL without recreating the type
