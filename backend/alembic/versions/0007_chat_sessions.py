"""Add chat sessions and attach existing conversation turns to them.

Revision ID: 0007_chat_sessions
Revises: 0006_citation_match_score
"""

from datetime import datetime, timezone
from uuid import uuid4

from alembic import op
import sqlalchemy as sa

revision = "0007_chat_sessions"
down_revision = "0006_citation_match_score"
branch_labels = None
depends_on = None

LEGACY_TITLE_LIMIT = 60


def _legacy_title(question: str | None) -> str:
    text = " ".join((question or "").split())
    if not text:
        return "Earlier conversation"
    return text if len(text) <= LEGACY_TITLE_LIMIT else text[: LEGACY_TITLE_LIMIT - 1].rstrip() + "\u2026"


def upgrade():
    op.create_table(
        "chat_sessions",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("space_id", sa.String(), sa.ForeignKey("research_spaces.id"), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("pinned", sa.Boolean(), nullable=False),
        sa.Column("archived", sa.Boolean(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("summary_turn_count", sa.Integer(), nullable=False),
        sa.Column("summary_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_chat_sessions_space_id", "chat_sessions", ["space_id"])
    with op.batch_alter_table("turns", recreate="always") as batch:
        batch.add_column(sa.Column("session_id", sa.String(), nullable=True))
        batch.add_column(sa.Column("mentions", sa.JSON(), nullable=True))
        batch.create_foreign_key("fk_turns_session_id_chat_sessions", "chat_sessions", ["session_id"], ["id"])
        batch.create_index("ix_turns_session_id", ["session_id"])

    # Preserve each space's existing single conversation as one session. Turns whose
    # space row is missing (legacy broken references) are left untouched so the
    # migration never introduces new foreign-key violations.
    bind = op.get_bind()
    spaces = bind.execute(sa.text(
        "SELECT t.space_id, MIN(t.created_at), MAX(t.created_at) FROM turns AS t "
        "JOIN research_spaces AS s ON s.id = t.space_id GROUP BY t.space_id"
    )).all()
    now = datetime.now(timezone.utc)
    for space_id, first_at, last_at in spaces:
        question = bind.execute(sa.text(
            "SELECT content FROM turns WHERE space_id = :space AND role = 'user' ORDER BY created_at LIMIT 1"
        ), {"space": space_id}).scalar()
        session_id = str(uuid4())
        bind.execute(sa.text(
            "INSERT INTO chat_sessions (id, space_id, title, pinned, archived, summary, summary_turn_count, "
            "summary_updated_at, created_at, updated_at) VALUES (:id, :space, :title, 0, 0, NULL, 0, NULL, :created, :updated)"
        ), {"id": session_id, "space": space_id, "title": _legacy_title(question), "created": first_at or now, "updated": last_at or now})
        bind.execute(sa.text("UPDATE turns SET session_id = :session WHERE space_id = :space"), {"session": session_id, "space": space_id})


def downgrade():
    raise NotImplementedError("Restore the pre-migration SQLite backup instead.")
