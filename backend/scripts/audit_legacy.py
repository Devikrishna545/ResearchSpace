"""Read-only legacy reference inventory. Does not repair, delete or fabricate evidence."""

import json
import sqlite3
from contextlib import closing
from pathlib import Path

from sqlalchemy.engine import make_url

from app.core.config import get_settings


def inspect(path: Path) -> dict:
    with closing(sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)) as db:
        if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise RuntimeError("Database integrity check failed")
        issues = []
        for table, rowid, parent, foreign_key in db.execute("PRAGMA foreign_key_check").fetchall():
            links = db.execute(f'PRAGMA foreign_key_list("{table}")').fetchall()
            column = next(link[3] for link in links if link[0] == foreign_key)
            columns = {entry[1] for entry in db.execute(f'PRAGMA table_info("{table}")')}
            key = "id" if "id" in columns else "space_id"
            identifier, target = db.execute(f'SELECT "{key}", "{column}" FROM "{table}" WHERE rowid = ?', (rowid,)).fetchone()
            issues.append({"table": table, "id": identifier, "column": column, "target_table": parent, "missing_id": target})
        tables = {name for (name,) in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        paper_ids = {row[0] for row in db.execute("SELECT id FROM papers")} if "papers" in tables else set()
        pin_ids = {row[0] for row in db.execute("SELECT paper_id FROM pins")} if "pins" in tables else set()
        unreferenced = sorted(paper_ids - pin_ids)
        comparisons = []
        if "comparison_reports" in tables:
            for report_id, raw_ids in db.execute("SELECT id, paper_ids FROM comparison_reports"):
                missing = sorted(set(json.loads(raw_ids or "[]")) - paper_ids)
                if missing:
                    comparisons.append({"report_id": report_id, "missing_paper_ids": missing})
    return {"foreign_key_violations": issues, "comparison_orphans": comparisons, "unreferenced_paper_ids": unreferenced}


def main() -> None:
    url = make_url(get_settings().database_url)
    if url.get_backend_name() != "sqlite" or not url.database or url.database == ":memory:":
        raise RuntimeError("Expected a persistent SQLite database URL")
    backend = Path(__file__).resolve().parents[1]
    path = Path(url.database)
    if not path.is_absolute():
        path = backend / path
    print(json.dumps(inspect(path.resolve()), indent=2))


if __name__ == "__main__":
    main()
