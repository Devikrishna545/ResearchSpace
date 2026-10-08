"""Local-only first-admin token regeneration. Never exposed through an API."""

import hashlib
import os
import secrets
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.engine import make_url

from app.core.config import get_settings


def main() -> None:
    url = make_url(get_settings().database_url)
    if url.get_backend_name() != "sqlite" or not url.database or url.database == ":memory:":
        raise RuntimeError("Setup token regeneration requires a persistent local SQLite database")
    backend = Path(__file__).resolve().parents[1]
    database = Path(url.database)
    if not database.is_absolute():
        database = backend / database
    database = database.resolve()
    path = database.parent / "setup-token"
    with sqlite3.connect(database, timeout=10) as db:
        db.execute("BEGIN IMMEDIATE")
        if db.execute("SELECT COUNT(*) FROM users").fetchone()[0]:
            raise RuntimeError("Setup token cannot be regenerated after an account exists")
        previous = path.read_text(encoding="utf-8").strip() if path.exists() else ""
        secret = secrets.token_urlsafe(32)
        hashed = hashlib.sha256(secret.encode()).hexdigest()
        temporary = path.with_name(f"setup-token.tmp-{secrets.token_hex(8)}")
        try:
            with temporary.open("x", encoding="utf-8") as stream:
                stream.write(hashed)
            os.chmod(temporary, 0o600)
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)
        audit = path.with_name("setup-token-audit.log")
        line = f"{datetime.now(timezone.utc).isoformat()} regenerated old={previous[:12]} new={hashed[:12]}\n"
        descriptor = os.open(audit, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        with os.fdopen(descriptor, "a", encoding="utf-8") as stream:
            stream.write(line)
        db.commit()
    print(f"ONE-TIME FIRST-ADMIN SETUP TOKEN: {secret}")


if __name__ == "__main__":
    main()
