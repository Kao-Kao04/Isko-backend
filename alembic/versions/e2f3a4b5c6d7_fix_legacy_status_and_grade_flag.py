"""fix legacy status drift and add has_grade_below_2_5

Revision ID: e2f3a4b5c6d7
Revises: d1e2f3a4b5c6
Create Date: 2026-05-10

Changes:
- One-time backfill: sync Application.status with main_status for any rows
  that drifted (e.g. screening_failed applications still showing as 'pending')
- Add has_grade_below_2_5 boolean to semester_records
"""
from alembic import op
import sqlalchemy as sa

revision = 'e2f3a4b5c6d7'
down_revision = 'd1e2f3a4b5c6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── Backfill corrupted Application.status rows ────────────────────────────
    # Any application whose main_status says REJECTED but legacy status is still
    # 'pending' was processed before the screening-failed sync fix was deployed.
    op.execute("""
        UPDATE applications
        SET status = 'rejected'
        WHERE main_status = 'rejected'
          AND status = 'pending'
    """)

    # Any application whose main_status says WITHDRAWN but legacy says 'pending'
    op.execute("""
        UPDATE applications
        SET status = 'withdrawn'
        WHERE main_status = 'withdrawn'
          AND status = 'pending'
    """)

    # Any application whose main_status says COMPLETION but legacy isn't 'approved'
    op.execute("""
        UPDATE applications
        SET status = 'approved'
        WHERE main_status = 'completion'
          AND status != 'approved'
    """)

    # ── Add has_grade_below_2_5 to semester_records ───────────────────────────
    op.add_column(
        'semester_records',
        sa.Column('has_grade_below_2_5', sa.Boolean(), nullable=False, server_default='false'),
    )


def downgrade() -> None:
    op.drop_column('semester_records', 'has_grade_below_2_5')
    # Note: the backfilled status values are not reversed — downgrade only
    # removes the new column.
