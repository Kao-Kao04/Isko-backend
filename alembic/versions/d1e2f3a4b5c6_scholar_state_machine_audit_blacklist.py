"""scholar state machine, system audit log, revoked tokens

Revision ID: d1e2f3a4b5c6
Revises: c2d3e4f5a6b7
Create Date: 2026-05-10

Changes:
- Add under_review, on_leave, suspended to scholarstatus enum
- Add scholar_status_logs table
- Add system_audit_logs table
- Add revoked_tokens table
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = 'd1e2f3a4b5c6'
down_revision = 'c2d3e4f5a6b7'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── Extend scholarstatus enum ─────────────────────────────────────────────
    # PostgreSQL requires ALTER TYPE outside a transaction for enum additions,
    # but Alembic's default transaction mode blocks that. We use COMMIT/BEGIN
    # workaround via execute_if + raw SQL.
    op.execute("ALTER TYPE scholarstatus ADD VALUE IF NOT EXISTS 'under_review'")
    op.execute("ALTER TYPE scholarstatus ADD VALUE IF NOT EXISTS 'on_leave'")
    op.execute("ALTER TYPE scholarstatus ADD VALUE IF NOT EXISTS 'suspended'")

    # ── scholar_status_logs ───────────────────────────────────────────────────
    op.create_table(
        'scholar_status_logs',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('scholar_id', sa.Integer(), sa.ForeignKey('scholars.id'), nullable=False),
        sa.Column('from_status', sa.Enum('active', 'probationary', 'under_review', 'on_leave',
                                         'suspended', 'terminated', 'graduated',
                                         name='scholarstatus'), nullable=True),
        sa.Column('to_status', sa.Enum('active', 'probationary', 'under_review', 'on_leave',
                                       'suspended', 'terminated', 'graduated',
                                       name='scholarstatus'), nullable=False),
        sa.Column('actor_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('reason', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    )
    op.create_index('ix_scholar_status_logs_scholar_id', 'scholar_status_logs', ['scholar_id'])

    # ── system_audit_logs ─────────────────────────────────────────────────────
    op.create_table(
        'system_audit_logs',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('actor_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('entity_type', sa.String(64), nullable=False),
        sa.Column('entity_id', sa.Integer(), nullable=True),
        sa.Column('action', sa.String(128), nullable=False),
        sa.Column('before_state', postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column('after_state', postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column('ip_address', sa.String(64), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    )
    op.create_index('ix_system_audit_logs_actor_id', 'system_audit_logs', ['actor_id'])
    op.create_index('ix_system_audit_logs_created_at', 'system_audit_logs', ['created_at'])

    # ── revoked_tokens ────────────────────────────────────────────────────────
    op.create_table(
        'revoked_tokens',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('token_hash', sa.String(64), nullable=False, unique=True),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    )
    op.create_index('ix_revoked_tokens_token_hash', 'revoked_tokens', ['token_hash'], unique=True)


def downgrade() -> None:
    op.drop_table('revoked_tokens')
    op.drop_table('system_audit_logs')
    op.drop_table('scholar_status_logs')
    # Note: PostgreSQL does not support removing enum values — downgrade leaves
    # under_review/on_leave/suspended in the enum, which is harmless.
