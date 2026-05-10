"""compliance stage, renewal tracking, document generation support

Revision ID: f3g4h5i6j7k8
Revises: e2f3a4b5c6d7
Create Date: 2026-05-10

Changes:
- Add max_semesters, requires_thank_you_letter to scholarships
- Add compliance_document_types table
- Add is_verified, verified_by, verified_at, notes to completion_requirements
- Add benefit_released, benefit_released_at, thank_you_submitted, thank_you_submitted_at
  to semester_records
"""
from alembic import op
import sqlalchemy as sa

revision = 'f3g4h5i6j7k8'
down_revision = 'e2f3a4b5c6d7'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── scholarships ──────────────────────────────────────────────────────────
    op.add_column('scholarships', sa.Column('max_semesters', sa.Integer(), nullable=True))
    op.add_column('scholarships', sa.Column(
        'requires_thank_you_letter', sa.Boolean(), nullable=False, server_default='false'
    ))

    # ── compliance_document_types ─────────────────────────────────────────────
    op.create_table(
        'compliance_document_types',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('scholarship_id', sa.Integer(), sa.ForeignKey('scholarships.id'), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('is_required', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('order', sa.Integer(), nullable=False, server_default='0'),
    )
    op.create_index('ix_compliance_doc_types_scholarship_id', 'compliance_document_types', ['scholarship_id'])

    # ── completion_requirements — add verification fields ─────────────────────
    op.add_column('completion_requirements', sa.Column('notes', sa.Text(), nullable=True))
    op.add_column('completion_requirements', sa.Column(
        'is_verified', sa.Boolean(), nullable=False, server_default='false'
    ))
    op.add_column('completion_requirements', sa.Column(
        'verified_by', sa.Integer(),
        sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True
    ))
    op.add_column('completion_requirements', sa.Column(
        'verified_at', sa.DateTime(timezone=True), nullable=True
    ))

    # ── semester_records — benefit + thank you tracking ───────────────────────
    op.add_column('semester_records', sa.Column(
        'benefit_released', sa.Boolean(), nullable=False, server_default='false'
    ))
    op.add_column('semester_records', sa.Column(
        'benefit_released_at', sa.DateTime(timezone=True), nullable=True
    ))
    op.add_column('semester_records', sa.Column(
        'thank_you_submitted', sa.Boolean(), nullable=False, server_default='false'
    ))
    op.add_column('semester_records', sa.Column(
        'thank_you_submitted_at', sa.DateTime(timezone=True), nullable=True
    ))


def downgrade() -> None:
    op.drop_column('semester_records', 'thank_you_submitted_at')
    op.drop_column('semester_records', 'thank_you_submitted')
    op.drop_column('semester_records', 'benefit_released_at')
    op.drop_column('semester_records', 'benefit_released')
    op.drop_column('completion_requirements', 'verified_at')
    op.drop_column('completion_requirements', 'verified_by')
    op.drop_column('completion_requirements', 'is_verified')
    op.drop_column('completion_requirements', 'notes')
    op.drop_table('compliance_document_types')
    op.drop_column('scholarships', 'requires_thank_you_letter')
    op.drop_column('scholarships', 'max_semesters')
