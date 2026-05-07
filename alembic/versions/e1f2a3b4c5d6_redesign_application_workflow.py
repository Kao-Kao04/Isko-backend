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
    main_status_enum.create(op.get_bind(), checkfirst=True)
    sub_status_enum.create(op.get_bind(), checkfirst=True)

    # New workflow columns on applications
    op.add_column('applications', sa.Column('main_status', main_status_enum, nullable=True))
    op.add_column('applications', sa.Column('sub_status',  sub_status_enum,  nullable=True))
    op.add_column('applications', sa.Column('screened_at',             sa.DateTime(timezone=True), nullable=True))
    op.add_column('applications', sa.Column('validated_at',            sa.DateTime(timezone=True), nullable=True))
    op.add_column('applications', sa.Column('interview_scheduled_at',  sa.DateTime(timezone=True), nullable=True))
    op.add_column('applications', sa.Column('interview_datetime',      sa.DateTime(timezone=True), nullable=True))
    op.add_column('applications', sa.Column('interview_completed_at',  sa.DateTime(timezone=True), nullable=True))
    op.add_column('applications', sa.Column('evaluated_at',            sa.DateTime(timezone=True), nullable=True))
    op.add_column('applications', sa.Column('decision_released_at',    sa.DateTime(timezone=True), nullable=True))
    op.add_column('applications', sa.Column('completion_submitted_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('applications', sa.Column('closed_at',               sa.DateTime(timezone=True), nullable=True))
    op.add_column('applications', sa.Column('interview_location',      sa.String(), nullable=True))
    op.add_column('applications', sa.Column('interview_notes',         sa.Text(),   nullable=True))
    op.add_column('applications', sa.Column('decision_remarks',        sa.Text(),   nullable=True))

    # Migrate existing data — cast to enum types explicitly
    op.execute("""
        UPDATE applications SET
            main_status = CASE status::text
                WHEN 'pending'    THEN 'application'
                WHEN 'incomplete' THEN 'verification'
                WHEN 'approved'   THEN 'completion'
                WHEN 'rejected'   THEN 'rejected'
                WHEN 'withdrawn'  THEN 'withdrawn'
                ELSE 'application'
            END::mainstatus,
            sub_status = CASE status::text
                WHEN 'pending'    THEN 'submitted'
                WHEN 'incomplete' THEN 'revision_requested'
                WHEN 'approved'   THEN 'completed'
                WHEN 'rejected'   THEN 'rejected'
                WHEN 'withdrawn'  THEN 'withdrawn'
                ELSE 'submitted'
            END::substatus
    """)

    # workflow_logs table
    op.create_table(
        'workflow_logs',
        sa.Column('id',             sa.Integer(), primary_key=True),
        sa.Column('application_id', sa.Integer(), sa.ForeignKey('applications.id'), nullable=False),
        sa.Column('changed_by',     sa.Integer(), sa.ForeignKey('users.id'),        nullable=False),
        sa.Column('from_main',      main_status_enum, nullable=True),
        sa.Column('from_sub',       sub_status_enum,  nullable=True),
        sa.Column('to_main',        main_status_enum, nullable=False),
        sa.Column('to_sub',         sub_status_enum,  nullable=False),
        sa.Column('note',           sa.Text(), nullable=True),
        sa.Column('created_at',     sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index('ix_workflow_logs_application_id', 'workflow_logs', ['application_id'])

    # completion_requirements table
    op.create_table(
        'completion_requirements',
        sa.Column('id',               sa.Integer(), primary_key=True),
        sa.Column('application_id',   sa.Integer(), sa.ForeignKey('applications.id'), nullable=False),
        sa.Column('requirement_type', sa.String(),  nullable=False),
        sa.Column('file_url',         sa.String(),  nullable=True),
        sa.Column('submitted_at',     sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at',       sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index('ix_completion_requirements_application_id', 'completion_requirements', ['application_id'])


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
