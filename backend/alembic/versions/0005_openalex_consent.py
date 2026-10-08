"""Store each member's explicit OpenAlex identification preference.

Revision ID: 0005_openalex_consent
Revises: 0004_note_chunk_fk
"""

from alembic import op
import sqlalchemy as sa

revision = "0005_openalex_consent"
down_revision = "0004_note_chunk_fk"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "openalex_consents",
        sa.Column("user_id", sa.String(), sa.ForeignKey("users.id"), primary_key=True),
        sa.Column("state", sa.String(), nullable=False),
        sa.Column("contact_email", sa.String(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("state IN ('unset', 'granted', 'declined')", name="ck_openalex_consent_state"),
    )


def downgrade():
    raise NotImplementedError("Restore the pre-migration SQLite backup instead.")
