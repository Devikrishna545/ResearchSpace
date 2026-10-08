"""Explicit, offline-disabled SQLite migrations; never invoked by application startup."""

import os
from pathlib import Path

from alembic import context
from dotenv import load_dotenv
from sqlalchemy import create_engine, event, inspect
from sqlalchemy.engine import make_url

from app.db.models import Base

config = context.config
load_dotenv(Path(config.config_file_name).parent / ".env", override=False)
target_metadata = Base.metadata


def database_url() -> str:
    url = os.environ.get("DATABASE_URL", config.get_main_option("sqlalchemy.url"))
    parsed = make_url(url)
    if parsed.get_backend_name() != "sqlite":
        raise RuntimeError("This migration series supports SQLite only")
    if parsed.drivername == "sqlite+aiosqlite":
        parsed = parsed.set(drivername="sqlite")
    elif parsed.drivername != "sqlite":
        raise RuntimeError(f"Unsupported SQLite driver: {parsed.drivername}")
    return parsed.render_as_string(hide_password=False)


if context.is_offline_mode():
    raise RuntimeError("Offline migration is unsafe: existing schema must be inspected")

engine = create_engine(database_url())


def _quoted(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _broken_links(connection) -> set[tuple[str, str, str, str, str]]:
    result = set()
    for table, rowid, parent, fk_index in connection.exec_driver_sql("PRAGMA foreign_key_check").all():
        table_info = connection.exec_driver_sql(f"PRAGMA table_info({_quoted(table)})").all()
        primary_key = next((row[1] for row in table_info if row[5] == 1), None)
        foreign_keys = connection.exec_driver_sql(f"PRAGMA foreign_key_list({_quoted(table)})").all()
        column = next(row[3] for row in foreign_keys if row[0] == fk_index)
        identifier_expr = _quoted(primary_key) if primary_key else "rowid"
        identifier, missing_id = connection.exec_driver_sql(
            f"SELECT {identifier_expr}, {_quoted(column)} FROM {_quoted(table)} WHERE rowid = ?", (rowid,)
        ).one()
        result.add((table, str(identifier), column, parent, str(missing_id)))
    return result


def _latent_note_chunks(connection) -> set[tuple[str, str, str, str, str]]:
    inspector = inspect(connection)
    if not {"notes", "chunks"} <= set(inspector.get_table_names()):
        return set()
    if "chunk_id" not in {column["name"] for column in inspector.get_columns("notes")}:
        return set()
    if any(fk["constrained_columns"] == ["chunk_id"] for fk in inspector.get_foreign_keys("notes")):
        return set()
    rows = connection.exec_driver_sql(
        "SELECT n.id, n.chunk_id FROM notes AS n WHERE n.chunk_id IS NOT NULL "
        "AND NOT EXISTS (SELECT 1 FROM chunks AS c WHERE c.id = n.chunk_id)"
    ).all()
    return {("notes", str(note_id), "chunk_id", "chunks", str(chunk_id)) for note_id, chunk_id in rows}


@event.listens_for(engine, "connect")
def disable_foreign_keys(dbapi_connection, _connection_record):
    # SQLite must switch FK enforcement outside a transaction for table rebuilds.
    dbapi_connection.execute("PRAGMA foreign_keys=OFF")


with engine.connect() as connection:
    existing_violations = _broken_links(connection)
    latent_note_chunks = _latent_note_chunks(connection)
    connection.commit()  # End the implicit read transaction before Alembic begins its own.
    context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()
    violations = _broken_links(connection)
    new_violations = violations - existing_violations - latent_note_chunks
    if new_violations:
        raise RuntimeError(f"New foreign-key violations after migration: {sorted(new_violations)[:5]}")
    if violations:
        import warnings

        warnings.warn(
            f"Preserved {len(violations)} legacy broken references "
            f"(including {len(violations & latent_note_chunks)} notes with previously unenforced chunk IDs); "
            "review these orphaned legacy records separately.",
            stacklevel=1,
        )
engine.dispose()
