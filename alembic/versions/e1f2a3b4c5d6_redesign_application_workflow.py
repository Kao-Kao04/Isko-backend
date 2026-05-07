"""redesign application workflow

Revision ID: e1f2a3b4c5d6
Revises: fed13430eeea
Create Date: 2026-05-06
"""
from alembic import op
import sqlalchemy as sa

revision = 'e1f2a3b4c5d6'
down_revision = 'fed13430eeea'
branch_labels = None
depends_on = None

main_status_enum = sa.Enum(
    'application', 'verification', 'interview', 'decision', 'completion',
    'withdrawn', 'rejected',
    name='mainstatus',
)
sub_status_enum = sa.Enum(
    'submitted', 'screening', 'screening_passed', 'screening_failed',
    'pending_validation', 'revision_requested', 'validated', 'validation_failed',
    'not_scheduled', 'scheduled', 'rescheduled', 'interview_completed', 'evaluated',
    'under_review', 'approved', 'rejected', 'waitlisted',
    'pending_requirements', 'requirements_submitted', 'completed',
    'withdrawn',
    name='substatus',
)


def upgrade() -> None:
    # Use DO block to safely create enums — handles already-exists from prior failed attempts
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE mainstatus AS ENUM (
                'application','verification','interview','decision','completion','withdrawn','rejected'
            );
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE substatus AS ENUM (
                'submitted','screening','screening_passed','screening_failed',
                'pending_validation','revision_requested','validated','validation_failed',
                'not_scheduled','scheduled','rescheduled','interview_completed','evaluated',
                'under_review','approved','rejected','waitlisted',
                'pending_requirements','requirements_submitted','completed',
                'withdrawn'
            );
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$;
    """)

    # Add columns with IF NOT EXISTS to survive re-runs after partial failures
    cols = [
        "ALTER TABLE applications ADD COLUMN IF NOT EXISTS main_status mainstatus",
        "ALTER TABLE applications ADD COLUMN IF NOT EXISTS sub_status substatus",
        "ALTER TABLE applications ADD COLUMN IF NOT EXISTS screened_at TIMESTAMPTZ",
        "ALTER TABLE applications ADD COLUMN IF NOT EXISTS validated_at TIMESTAMPTZ",
        "ALTER TABLE applications ADD COLUMN IF NOT EXISTS interview_scheduled_at TIMESTAMPTZ",
        "ALTER TABLE applications ADD COLUMN IF NOT EXISTS interview_datetime TIMESTAMPTZ",
        "ALTER TABLE applications ADD COLUMN IF NOT EXISTS interview_completed_at TIMESTAMPTZ",
        "ALTER TABLE applications ADD COLUMN IF NOT EXISTS evaluated_at TIMESTAMPTZ",
        "ALTER TABLE applications ADD COLUMN IF NOT EXISTS decision_released_at TIMESTAMPTZ",
        "ALTER TABLE applications ADD COLUMN IF NOT EXISTS completion_submitted_at TIMESTAMPTZ",
        "ALTER TABLE applications ADD COLUMN IF NOT EXISTS closed_at TIMESTAMPTZ",
        "ALTER TABLE applications ADD COLUMN IF NOT EXISTS interview_location VARCHAR",
        "ALTER TABLE applications ADD COLUMN IF NOT EXISTS interview_notes TEXT",
        "ALTER TABLE applications ADD COLUMN IF NOT EXISTS decision_remarks TEXT",
    ]
    for col in cols:
        op.execute(col)

    # Existing applications start with NULL main_status/sub_status.
    # OSFA staff can initialize them via POST /api/workflow/{id}/initialize.

    # workflow_logs table
    op.execute("""
        CREATE TABLE IF NOT EXISTS workflow_logs (
            id SERIAL PRIMARY KEY,
            application_id INTEGER NOT NULL REFERENCES applications(id),
            changed_by INTEGER NOT NULL REFERENCES users(id),
            from_main mainstatus,
            from_sub substatus,
            to_main mainstatus NOT NULL,
            to_sub substatus NOT NULL,
            note TEXT,
            created_at TIMESTAMPTZ DEFAULT NOW()
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_workflow_logs_application_id ON workflow_logs(application_id)")

    # completion_requirements table
    op.execute("""
        CREATE TABLE IF NOT EXISTS completion_requirements (
            id SERIAL PRIMARY KEY,
            application_id INTEGER NOT NULL REFERENCES applications(id),
            requirement_type VARCHAR NOT NULL,
            file_url VARCHAR,
            submitted_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ DEFAULT NOW()
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_completion_requirements_application_id ON completion_requirements(application_id)")


def downgrade() -> None:
    op.drop_table('completion_requirements')
    op.drop_table('workflow_logs')
    for col in [
        'main_status', 'sub_status', 'screened_at', 'validated_at',
        'interview_scheduled_at', 'interview_datetime', 'interview_completed_at',
        'evaluated_at', 'decision_released_at', 'completion_submitted_at',
        'closed_at', 'interview_location', 'interview_notes', 'decision_remarks',
    ]:
        op.drop_column('applications', col)
    main_status_enum.drop(op.get_bind(), checkfirst=True)
    sub_status_enum.drop(op.get_bind(), checkfirst=True)
