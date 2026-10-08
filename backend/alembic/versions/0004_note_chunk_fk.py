"""Restore the note chunk FK omitted by historical startup ALTER TABLE.

Revision ID: 0004_note_chunk_fk
Revises: 0003_linkedin_connection
"""

from alembic import op
import sqlalchemy as sa

revision = "0004_note_chunk_fk"
down_revision = "0003_linkedin_connection"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("notes")}
    if "chunk_id" not in columns:
        raise RuntimeError("Cannot restore notes.chunk_id FK: column is missing")
    chunk_links = [
        fk for fk in inspector.get_foreign_keys("notes")
        if fk["constrained_columns"] == ["chunk_id"]
    ]
    if chunk_links:
        if len(chunk_links) != 1 or chunk_links[0]["referred_table"] != "chunks" or chunk_links[0]["referred_columns"] != ["id"]:
            raise RuntimeError("Unexpected notes.chunk_id foreign key; refusing to replace it")
        return
    with op.batch_alter_table("notes", recreate="always") as batch:
        batch.create_foreign_key("fk_notes_chunk_id_chunks", "chunks", ["chunk_id"], ["id"])


def downgrade():
    raise NotImplementedError("Restore the pre-migration SQLite backup instead.")
