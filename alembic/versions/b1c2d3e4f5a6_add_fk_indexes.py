"""add FK indexes for performance

Revision ID: b1c2d3e4f5a6
Revises: f1a2b3c4d5e6
Create Date: 2026-05-09
"""
from alembic import op

revision = 'b1c2d3e4f5a6'
down_revision = 'f1a2b3c4d5e6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_applications_student_id    ON applications(student_id)")
    op.execute("CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_applications_scholarship_id ON applications(scholarship_id)")
    op.execute("CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_notifications_user_id       ON notifications(user_id)")
    op.execute("CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_app_documents_application_id ON application_documents(application_id)")
    op.execute("CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_scholars_student_id         ON scholars(student_id)")
    op.execute("CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_scholars_scholarship_id     ON scholars(scholarship_id)")
    op.execute("CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_audit_entries_application_id ON audit_entries(application_id)")
    op.execute("CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_workflow_logs_application_id ON workflow_logs(application_id)")


def downgrade() -> None:
    for idx in [
        "ix_applications_student_id", "ix_applications_scholarship_id",
        "ix_notifications_user_id", "ix_app_documents_application_id",
        "ix_scholars_student_id", "ix_scholars_scholarship_id",
        "ix_audit_entries_application_id", "ix_workflow_logs_application_id",
    ]:
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {idx}")
