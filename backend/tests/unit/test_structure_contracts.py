"""Contract fingerprints, updated for explicit schema and prompt changes."""

import hashlib
import importlib
import json
import pkgutil
from pathlib import Path

from sqlalchemy.dialects.sqlite import dialect
from sqlalchemy.schema import CreateIndex, CreateTable

import app
from app.db.models import Base
from app.main import create_app
from app.modules.papers.ingestion.upload import PROJECT_ROOT
from app.platform.llm.prompts.loader import PromptLoader


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def test_openapi_matches_pre_migration_contract():
    schema = create_app().openapi()
    assert len(schema["paths"]) == 59
    assert fingerprint(schema) == "452c6e7700720a99266541fb3c7ab799fdc51cc0b2fa6d08f9c7ab3a88e2378c"


def test_tables_constraints_and_indexes_match_contract():
    definitions = {
        table.name: {
            "ddl": str(CreateTable(table).compile(dialect=dialect())),
            "indexes": sorted(str(CreateIndex(index).compile(dialect=dialect())) for index in table.indexes),
        }
        for table in Base.metadata.sorted_tables
    }
    assert len(definitions) == 26
    assert fingerprint(definitions) == "fa51ffce6fef5e501f91f5cdd3b441b067455760d20681746d5ba42074243cf0"


def test_all_moved_modules_import():
    modules = list(pkgutil.walk_packages(app.__path__, "app."))
    assert any(item.name == "app.modules.compare.grounded.jobs" for item in modules)
    for item in modules:
        importlib.import_module(item.name)


def test_prompt_assets_and_upload_boundary_survive_relocation():
    root = PromptLoader().base_dir.parent
    assets = {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in root.rglob("*")
        if path.is_file() and path.suffix in {".jinja", ".yaml"}
    }
    assert len(assets) == 30
    assert fingerprint(assets) == "e161aa857d3a977a9faf04a99fda5d7f7782fbbca3c094dd1c345da8ec00cf0c"
    assert PROJECT_ROOT == Path(__file__).resolve().parents[3]


def test_compatibility_imports_share_router_and_database_state():
    from app.api import router as compatibility
    from app.api.v1.router import api_router
    from app.core import dependencies
    from app.db import session

    assert compatibility.api_router is api_router
    assert dependencies.SessionLocal is session.SessionLocal
    assert dependencies.engine is session.engine
    assert dependencies.get_db_session is session.get_db_session
