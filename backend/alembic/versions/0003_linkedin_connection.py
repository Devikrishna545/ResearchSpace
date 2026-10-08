"""Optional encrypted member publishing connection and one-shot posting attempts.

Revision ID: 0003_linkedin_connection
Revises: 0002_account_ownership
"""

from alembic import op
import sqlalchemy as sa

revision = "0003_linkedin_connection"
down_revision = "0002_account_ownership"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "legacy_claim_audits",
        sa.Column("user_id", sa.String(), sa.ForeignKey("users.id"), primary_key=True),
        sa.Column("foreign_key_violations", sa.JSON(), nullable=False),
        sa.Column("comparison_orphans", sa.JSON(), nullable=False),
        sa.Column("unreferenced_paper_ids", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "linkedin_oauth_states",
        sa.Column("state_hash", sa.String(), primary_key=True),
        sa.Column("user_id", sa.String(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("session_hash", sa.String(), sa.ForeignKey("auth_sessions.token_hash", ondelete="CASCADE"), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "linkedin_connections",
        sa.Column("user_id", sa.String(), sa.ForeignKey("users.id"), primary_key=True),
        sa.Column("encrypted_token", sa.Text(), nullable=False),
        sa.Column("member_id", sa.String(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "linkedin_post_attempts",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("user_id", sa.String(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("request_id", sa.String(), nullable=False),
        sa.Column("source_type", sa.String(), nullable=False),
        sa.Column("source_id", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("result_urn", sa.String(), nullable=True),
        sa.UniqueConstraint("user_id", "request_id", name="uq_linkedin_post_request"),
    )


def downgrade():
    raise NotImplementedError("Restore the pre-migration SQLite backup instead.")
