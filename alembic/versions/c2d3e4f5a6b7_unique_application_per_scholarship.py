"""unique constraint: one active application per student per scholarship

Revision ID: c2d3e4f5a6b7
Revises: b1c2d3e4f5a6
Create Date: 2026-05-10
"""
from alembic import op

revision = 'c2d3e4f5a6b7'
down_revision = 'b1c2d3e4f5a6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS
        uix_active_application ON applications(student_id, scholarship_id)
        WHERE status != 'withdrawn'
    """)


def downgrade() -> None:
    op.execute("DROP INDEX CONCURRENTLY IF EXISTS uix_active_application")
