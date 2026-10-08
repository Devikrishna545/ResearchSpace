"""Migrations run only against disposable databases under backend/tests."""

import importlib.util
from contextlib import closing
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import uuid

import pytest
from sqlalchemy import create_engine


HEAD = "0009_chat_verification_metadata"
GROUNDED_TABLES = {"paper_evidence_builds", "document_artifacts", "evidence_facts", "llm_call_logs", "analysis_jobs", "comparison_findings", "literature_corpus_items"}


BACKEND = Path(__file__).resolve().parents[3]
REVISION = BACKEND / "alembic" / "versions" / "0001_legacy_baseline.py"
spec = importlib.util.spec_from_file_location("legacy_baseline", REVISION)
legacy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(legacy)


@pytest.fixture
def db_path():
    folder = BACKEND / "tests" / f".migration-{uuid.uuid4().hex}"
    folder.mkdir()
    yield folder / "test.db"
    shutil.rmtree(folder)


def run_alembic(path, *args, success=True):
    env = os.environ.copy()
    env["DATABASE_URL"] = f"sqlite:///{path.as_posix()}"
    result = subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=BACKEND, env=env, capture_output=True, text=True,
    )
    if success:
        assert result.returncode == 0, result.stdout + result.stderr
    else:
        assert result.returncode != 0
    return result


def inspect(path):
    with closing(sqlite3.connect(path)) as db, db:
        names = {row[0] for row in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )}
        version = db.execute("SELECT version_num FROM alembic_version").fetchone()[0]
        violations = db.execute("PRAGMA foreign_key_check").fetchall()
        return names, version, violations


def test_fresh_upgrade_and_scoped_identifiers(db_path):
    run_alembic(db_path, "upgrade", "head")
    names, version, violations = inspect(db_path)
    assert names == set(legacy.m.tables) | {"auth_sessions", "alembic_version", "linkedin_oauth_states", "linkedin_connections", "linkedin_post_attempts",     "legacy_claim_audits", "openalex_consents", "chat_sessions"} | GROUNDED_TABLES
    assert version == HEAD
    assert not violations
    with closing(sqlite3.connect(db_path)) as db:
        assert any(row[3] == "chunk_id" and row[2] == "chunks" for row in db.execute("PRAGMA foreign_key_list(notes)"))
        assert any(row[1] == "match_score" and row[3] == 0 for row in db.execute("PRAGMA table_info(citations)"))
        assert any(row[1] == "answer_metadata" and row[3] == 0 for row in db.execute("PRAGMA table_info(turns)"))
        assert any(row[1] == "verdict_json" and row[3] == 0 for row in db.execute("PRAGMA table_info(verification_iterations)"))
    run_alembic(db_path, "check")
    with closing(sqlite3.connect(db_path)) as db, db:
        for user in ("a", "b"):
            db.execute(
                "INSERT INTO users(id,email,created_at) VALUES (?,?,?)",
                (user, f"{user}@example.test", "2026-01-01"),
            )
        db.execute("INSERT INTO openalex_consents(user_id,state,updated_at) VALUES ('a','unset','2026-01-01')")
        db.execute("INSERT INTO openalex_consents(user_id,state,updated_at) VALUES ('b','declined','2026-01-01')")
        assert db.execute("SELECT user_id,state,contact_email FROM openalex_consents ORDER BY user_id").fetchall() == [
            ("a", "unset", None), ("b", "declined", None),
        ]
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("INSERT INTO openalex_consents(user_id,state,updated_at) VALUES ('invalid','implicit','2026-01-01')")
        for owner in ("a", "b"):
            db.execute(
                """INSERT INTO papers(id,owner_id,doi,title,authors,citation_count,
                   ingest_status,raw_payload,created_at)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (owner, owner, "same-doi", "Title", "[]", 0, "QUEUED", "{}", "2026-01-01"),
            )
        assert db.execute("SELECT COUNT(*) FROM papers").fetchone()[0] == 2
        with pytest.raises(sqlite3.IntegrityError):
            db.execute(
                """INSERT INTO papers(id,owner_id,doi,title,authors,citation_count,
                   ingest_status,raw_payload,created_at)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                ("duplicate", "a", "same-doi", "Title", "[]", 0, "QUEUED", "{}", "2026-01-01"),
            )


@pytest.mark.parametrize("older_columns", [False, True])
def test_legacy_upgrade_preserves_rows(db_path, older_columns):
    engine = create_engine(f"sqlite:///{db_path.as_posix()}")
    legacy.m.create_all(engine)
    engine.dispose()
    with closing(sqlite3.connect(db_path)) as db, db:
        if older_columns:
            db.execute("PRAGMA foreign_keys=OFF")
            db.execute("DROP TABLE notes")
            db.execute(
                """CREATE TABLE notes (
                    id VARCHAR NOT NULL PRIMARY KEY, space_id VARCHAR NOT NULL,
                    paper_id VARCHAR, content TEXT NOT NULL, source VARCHAR NOT NULL,
                    created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL,
                    FOREIGN KEY(space_id) REFERENCES research_spaces(id),
                    FOREIGN KEY(paper_id) REFERENCES papers(id)
                )"""
            )
            for col in ("paper_id", "section", "page", "quote"):
                db.execute(f"ALTER TABLE citations DROP COLUMN {col}")
        db.execute(
            "INSERT INTO users(id,email,created_at) VALUES ('u','u@example.test','2026-01-01')"
        )
        db.execute(
            """INSERT INTO research_spaces(id,name,status,created_at,updated_at)
               VALUES ('s','Preserve me','active','2026-01-01','2026-01-01')"""
        )
        db.execute(
            """INSERT INTO papers(id,doi,title,authors,citation_count,ingest_status,
               raw_payload,created_at)
               VALUES ('p','10/test','Preserve paper','[]',0,'QUEUED','{}','2026-01-01')"""
        )
        db.execute(
            """INSERT INTO chunks(id,paper_id,ordinal,text,token_count)
               VALUES ('c','p',0,'Evidence',1)"""
        )
        db.execute(
            """INSERT INTO turns(id,space_id,role,content,created_at)
               VALUES ('t','s','user','Question','2026-01-01')"""
        )
        db.execute("INSERT INTO citations(id,turn_id,chunk_id,ordinal) VALUES ('q','t','c',0)")
        db.execute(
            """INSERT INTO notes(id,space_id,paper_id,content,source,created_at,updated_at)
               VALUES ('n','s','p','Do not lose me','manual','2026-01-01','2026-01-01')"""
        )
    run_alembic(db_path, "upgrade", "head")
    _, version, violations = inspect(db_path)
    assert version == HEAD
    assert not violations
    with closing(sqlite3.connect(db_path)) as db, db:
        assert db.execute("SELECT content FROM notes WHERE id='n'").fetchone() == ("Do not lose me",)
        assert db.execute("SELECT doi,owner_id FROM papers WHERE id='p'").fetchone() == ("10/test", None)
        assert db.execute("SELECT is_admin,password_hash FROM users WHERE id='u'").fetchone() == (0, None)
        assert db.execute("SELECT paper_id FROM citations WHERE id='q'").fetchone() == (None,)
        assert db.execute("SELECT user_id FROM research_spaces WHERE id='s'").fetchone() == (None,)
        assert db.execute("SELECT COUNT(*) FROM openalex_consents").fetchone()[0] == 0
        assert any(row[3] == "chunk_id" and row[2] == "chunks" for row in db.execute("PRAGMA foreign_key_list(notes)"))
    run_alembic(db_path, "upgrade", "head")
    run_alembic(db_path, "check")


def test_legacy_note_chunk_column_without_fk_preserves_rows(db_path):
    engine = create_engine(f"sqlite:///{db_path.as_posix()}")
    legacy.m.create_all(engine)
    engine.dispose()
    with closing(sqlite3.connect(db_path)) as db, db:
        db.execute("PRAGMA foreign_keys=OFF")
        db.execute("DROP TABLE notes")
        db.execute(
            """CREATE TABLE notes (
                id VARCHAR NOT NULL PRIMARY KEY, space_id VARCHAR NOT NULL,
                paper_id VARCHAR, content TEXT NOT NULL, source VARCHAR NOT NULL,
                chunk_id VARCHAR, anchor_quote TEXT, anchor_start INTEGER,
                anchor_end INTEGER, color VARCHAR, created_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL,
                FOREIGN KEY(space_id) REFERENCES research_spaces(id),
                FOREIGN KEY(paper_id) REFERENCES papers(id)
            )"""
        )
        db.execute("INSERT INTO research_spaces(id,name,status,created_at,updated_at) VALUES ('s','Legacy','active','2026-01-01','2026-01-01')")
        db.execute("INSERT INTO papers(id,title,authors,citation_count,ingest_status,raw_payload,created_at) VALUES ('p','Paper','[]',0,'READY','{}','2026-01-01')")
        db.execute("INSERT INTO chunks(id,paper_id,ordinal,text,token_count) VALUES ('c','p',0,'Original evidence',2)")
        db.execute(
            """INSERT INTO notes(id,space_id,paper_id,content,source,chunk_id,anchor_quote,anchor_start,anchor_end,color,created_at,updated_at)
               VALUES ('valid','s','p','Keep annotation','manual','c','Original',0,8,'amber','2026-01-01','2026-01-01')"""
        )
        db.execute(
            """INSERT INTO notes(id,space_id,paper_id,content,source,chunk_id,anchor_quote,created_at,updated_at)
               VALUES ('orphan','s','missing-paper','Preserve broken anchor','manual','missing-chunk','Do not fabricate','2026-01-01','2026-01-01')"""
        )
        before = db.execute("SELECT id,space_id,paper_id,content,source,chunk_id,anchor_quote,anchor_start,anchor_end,color,created_at,updated_at FROM notes ORDER BY id").fetchall()
        assert len(db.execute("PRAGMA foreign_key_check").fetchall()) == 1
    run_alembic(db_path, "upgrade", "head")
    with closing(sqlite3.connect(db_path)) as db:
        assert db.execute("SELECT id,space_id,paper_id,content,source,chunk_id,anchor_quote,anchor_start,anchor_end,color,created_at,updated_at FROM notes ORDER BY id").fetchall() == before
        assert {row[2:5] for row in db.execute("PRAGMA foreign_key_list(notes)")} >= {
            ("chunks", "chunk_id", "id"), ("papers", "paper_id", "id"), ("research_spaces", "space_id", "id"),
        }
        assert len(db.execute("PRAGMA foreign_key_check").fetchall()) == 2
    run_alembic(db_path, "check")
    run_alembic(db_path, "upgrade", "head")


def test_unrecognized_legacy_schema_is_never_stamped(db_path):
    engine = create_engine(f"sqlite:///{db_path.as_posix()}")
    legacy.m.create_all(engine)
    engine.dispose()
    with closing(sqlite3.connect(db_path)) as db, db:
        db.execute("ALTER TABLE papers ADD COLUMN surprise VARCHAR")
    output = run_alembic(db_path, "upgrade", "head", success=False)
    assert "Unrecognized papers columns" in output.stderr
    with closing(sqlite3.connect(db_path)) as db, db:
        assert db.execute("SELECT COUNT(*) FROM alembic_version").fetchone()[0] == 0
        assert "is_admin" not in {row[1] for row in db.execute("PRAGMA table_info(users)")}


def test_legacy_orphans_are_preserved_not_multiplied(db_path):
    engine = create_engine(f"sqlite:///{db_path.as_posix()}")
    legacy.m.create_all(engine)
    engine.dispose()
    with closing(sqlite3.connect(db_path)) as db, db:
        db.execute(
            """INSERT INTO pins(id,space_id,paper_id,pinned_at)
               VALUES ('old-pin','deleted-space','deleted-paper','2026-01-01')"""
        )
        original = db.execute("PRAGMA foreign_key_check").fetchall()
        assert len(original) == 2
    run_alembic(db_path, "upgrade", "head")
    with closing(sqlite3.connect(db_path)) as db:
        assert db.execute("SELECT paper_id FROM pins WHERE id='old-pin'").fetchone() == (
            "deleted-paper",
        )
        assert db.execute("PRAGMA foreign_key_check").fetchall() == original


def test_controlled_runner_retains_backup_and_preserves_rows(db_path):
    engine = create_engine(f"sqlite:///{db_path.as_posix()}")
    legacy.m.create_all(engine)
    engine.dispose()
    with closing(sqlite3.connect(db_path)) as db, db:
        db.execute("INSERT INTO users(id,email,created_at) VALUES ('u','u@example.com','2026-01-01')")
    env = {**os.environ, "DATABASE_URL": f"sqlite+aiosqlite:///{db_path.as_posix()}"}
    result = subprocess.run(
        [sys.executable, "-m", "scripts.migrate"], cwd=BACKEND,
        env=env, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    backups = list(db_path.parent.glob("test.pre-alembic-*.db"))
    assert len(backups) == 1
    with closing(sqlite3.connect(backups[0])) as backup, closing(sqlite3.connect(db_path)) as migrated:
        assert backup.execute("SELECT id FROM users").fetchall() == migrated.execute("SELECT id FROM users").fetchall()
        assert migrated.execute("SELECT version_num FROM alembic_version").fetchone()[0] == HEAD


@pytest.mark.skipif(not (BACKEND / "data" / "legacy-backup.db").exists(), reason="Local real-db copy is not distributed with source")
def test_real_legacy_backup_upgrade_on_disposable_copy(db_path):
    shutil.copy2(BACKEND / "data" / "legacy-backup.db", db_path)
    with closing(sqlite3.connect(db_path)) as db:
        notes_before = db.execute("SELECT * FROM notes ORDER BY id").fetchall()
        assert len(db.execute("PRAGMA foreign_key_check").fetchall()) == 16
        assert db.execute(
            "SELECT COUNT(*) FROM notes n WHERE n.chunk_id IS NOT NULL AND NOT EXISTS "
            "(SELECT 1 FROM chunks c WHERE c.id=n.chunk_id)"
        ).fetchone()[0] == 1
    run_alembic(db_path, "upgrade", "head")
    with closing(sqlite3.connect(db_path)) as db:
        assert db.execute("SELECT * FROM notes ORDER BY id").fetchall() == notes_before
        assert len(db.execute("PRAGMA foreign_key_check").fetchall()) == 17
        assert any(row[3] == "chunk_id" and row[2] == "chunks" for row in db.execute("PRAGMA foreign_key_list(notes)"))
    run_alembic(db_path, "check")


def test_existing_turns_become_one_chat_session_per_space(db_path):
    engine = create_engine(f"sqlite:///{db_path.as_posix()}")
    legacy.m.create_all(engine)
    engine.dispose()
    with closing(sqlite3.connect(db_path)) as db, db:
        db.execute("INSERT INTO research_spaces(id,name,status,created_at,updated_at) VALUES ('s','Space','active','2026-01-01','2026-01-01')")
        db.execute("INSERT INTO research_spaces(id,name,status,created_at,updated_at) VALUES ('quiet','No chat','active','2026-01-01','2026-01-01')")
        db.execute("INSERT INTO turns(id,space_id,role,content,created_at) VALUES ('q1','s','user','  What does   the evidence say about retrieval augmented generation in low-resource settings?','2026-01-01 10:00:00')")
        db.execute("INSERT INTO turns(id,space_id,role,content,created_at) VALUES ('a1','s','assistant','Answer','2026-01-01 10:00:01')")
        db.execute("INSERT INTO turns(id,space_id,role,content,created_at) VALUES ('orphan','gone','user','Lost space','2026-01-01')")
        original = db.execute("PRAGMA foreign_key_check").fetchall()
    run_alembic(db_path, "upgrade", "head")
    with closing(sqlite3.connect(db_path)) as db:
        sessions = db.execute("SELECT id,space_id,title,pinned,archived,summary_turn_count FROM chat_sessions").fetchall()
        assert len(sessions) == 1
        session_id, space_id, title, pinned, archived, covered = sessions[0]
        assert (space_id, pinned, archived, covered) == ("s", 0, 0, 0)
        assert title.startswith("What does the evidence say") and len(title) <= 60
        assert db.execute("SELECT id,session_id FROM turns ORDER BY id").fetchall() == [("a1", session_id), ("orphan", None), ("q1", session_id)]
        assert db.execute("PRAGMA foreign_key_check").fetchall() == original
        assert any(row[2] == "chat_sessions" and row[3] == "session_id" for row in db.execute("PRAGMA foreign_key_list(turns)"))
    run_alembic(db_path, "check")
