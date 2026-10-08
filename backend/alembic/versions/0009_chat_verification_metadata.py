"""Preserve final chat metadata and complete reviewer verdicts."""

from alembic import op
import sqlalchemy as sa

revision = "0009_chat_verification_metadata"
down_revision = "0008_grounded_compare"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("turns", sa.Column("answer_metadata", sa.JSON(), nullable=True))
    op.add_column("verification_iterations", sa.Column("verdict_json", sa.JSON(), nullable=True))


def downgrade():
    op.drop_column("verification_iterations", "verdict_json")
    op.drop_column("turns", "answer_metadata")
