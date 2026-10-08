"""Persist measured claim-to-citation similarity for new citations.

Revision ID: 0006_citation_match_score
Revises: 0005_openalex_consent
"""

from alembic import op
import sqlalchemy as sa

revision = "0006_citation_match_score"
down_revision = "0005_openalex_consent"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("citations", sa.Column("match_score", sa.Float(), nullable=True))


def downgrade():
    raise NotImplementedError("Restore the pre-migration SQLite backup instead.")
