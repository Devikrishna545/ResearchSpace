"""Run SQLite Alembic upgrades with a consistent, retained pre-upgrade backup."""

import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.engine import make_url

from app.core.config import get_settings

BACKEND = Path(__file__).resolve().parents[1]


def snapshot(path: Path) -> tuple[Path, dict[str, int]]:
    backup = path.with_name(f"{path.stem}.pre-alembic-{datetime.now(timezone.utc):%Y%m%dT%H%M%S%fZ}{path.suffix}")
    with sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True) as source, sqlite3.connect(backup) as target:
        source.backup(target)
        if target.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise RuntimeError(f"Backup failed integrity check: {backup}")
        counts = {
            table: target.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
            for (table,) in target.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' AND name != 'alembic_version'"
            )
        }
        violations = target.execute("PRAGMA foreign_key_check").fetchall()
    print(f"Backup retained: {backup}", flush=True)
    if violations:
        print(f"Pre-existing foreign-key violations in backup: {len(violations)}", flush=True)
    return backup, counts


def main() -> int:
    url = make_url(get_settings().database_url)
    if url.get_backend_name() != "sqlite" or not url.database or url.database == ":memory:":
        raise RuntimeError("This migration runner requires a persistent SQLite database")
    path = Path(url.database)
    if not path.is_absolute():
        path = BACKEND / path
    path = path.resolve()
    backup, original = snapshot(path) if path.exists() else (None, {})
    try:
        subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=BACKEND, check=True)
        with sqlite3.connect(path) as db:
            if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise RuntimeError("Migrated database failed integrity check")
            for table, count in original.items():
                actual = db.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
                if actual != count:
                    raise RuntimeError(f"Row count changed in {table}: {count} -> {actual}")
    except (subprocess.CalledProcessError, sqlite3.DatabaseError, RuntimeError) as exc:
        print(f"Migration not verified: {exc}", file=sys.stderr)
        if backup:
            print(f"Stop all database connections before restoring the retained backup: {backup}", file=sys.stderr)
        return 1
    print("Migration complete and existing row counts verified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
