"""Add credentials/session storage and owner-scoped paper identifiers.

Revision ID: 0002_account_ownership
Revises: 0001_legacy_baseline
"""

from alembic import op
import sqlalchemy as sa

revision = "0002_account_ownership"
down_revision = "0001_legacy_baseline"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "users", sa.Column("is_admin", sa.Boolean(), nullable=False, server_default=sa.false())
    )
    op.create_table(
        "auth_sessions",
        sa.Column("token_hash", sa.String(), primary_key=True),
        sa.Column("user_id", sa.String(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("idle_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("absolute_expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_auth_sessions_user_id", "auth_sessions", ["user_id"])
    # SQLite unnamed UNIQUE constraints require synthetic names for batch drop.
    with op.batch_alter_table(
        "papers", recreate="always",
        naming_convention={"uq": "uq_%(table_name)s_%(column_0_name)s"},
    ) as batch:
        batch.add_column(sa.Column("owner_id", sa.String(), nullable=True))
        batch.create_foreign_key("fk_papers_owner_id_users", "users", ["owner_id"], ["id"])
        for column in ("doi", "arxiv_id", "content_hash"):
            batch.drop_constraint(f"uq_papers_{column}", type_="unique")
            batch.create_unique_constraint(
                f"uq_paper_owner_{column}", ["owner_id", column]
            )
    op.create_index("ix_papers_owner_id", "papers", ["owner_id"])


def downgrade():
    raise NotImplementedError("Restore the pre-migration SQLite backup instead.")
