"""Create the historical schema or adopt a verified create_all-managed SQLite database.

Revision ID: 0001_legacy_baseline
Revises:
"""

from alembic import op
import sqlalchemy as sa

revision = "0001_legacy_baseline"
down_revision = None
branch_labels = None
depends_on = None

m = sa.MetaData()
S, I, T, J, D, F, B = (
    sa.String, sa.Integer, sa.Text, sa.JSON, sa.DateTime, sa.Float, sa.Boolean
)


def c(name, typ=S, *, pk=False, optional=False, fk=None, unique=False):
    return sa.Column(
        name, typ, *([sa.ForeignKey(fk)] if fk else []),
        primary_key=pk, nullable=optional, unique=unique,
    )


sa.Table("users", m, c("id", pk=True), c("email", unique=False),
         c("password_hash", optional=True), c("created_at", D),
         sa.Index("ix_users_email", "email", unique=True))
sa.Table("research_spaces", m, c("id", pk=True),
         c("user_id", fk="users.id", optional=True), c("name"), c("status"),
         c("created_at", D), c("updated_at", D))
sa.Table("papers", m, c("id", pk=True), c("doi", optional=True, unique=True),
         c("arxiv_id", optional=True, unique=True), c("pmid", optional=True),
         c("openalex_id", optional=True), c("title", T), c("authors", J),
         c("year", I, optional=True), c("venue", optional=True),
         c("abstract", T, optional=True), c("citation_count", I),
         c("oa_status", optional=True), c("pdf_url", optional=True),
         c("source", optional=True), c("content_hash", optional=True, unique=True),
         c("ingest_status"), c("raw_payload", J), c("created_at", D))
sa.Table("pins", m, c("id", pk=True), c("space_id", fk="research_spaces.id"),
         c("paper_id", fk="papers.id"), c("pinned_at", D),
         sa.UniqueConstraint("space_id", "paper_id", name="uq_pin_space_paper"))
sa.Table("chunks", m, c("id", pk=True), c("paper_id", fk="papers.id"),
         c("section", optional=True), c("page", I, optional=True),
         c("ordinal", I), c("text", T), c("token_count", I),
         c("vector_id", optional=True), c("embedding_json", J, optional=True))
sa.Table("turns", m, c("id", pk=True), c("space_id", fk="research_spaces.id"),
         c("role"), c("content", T), c("created_at", D))
sa.Table("citations", m, c("id", pk=True), c("turn_id", fk="turns.id"),
         c("chunk_id", fk="chunks.id"), c("paper_id", optional=True),
         c("section", optional=True), c("page", I, optional=True),
         c("quote", T, optional=True), c("claim_text", T, optional=True),
         c("ordinal", I))
sa.Table("verification_iterations", m, c("id", pk=True),
         c("turn_id", fk="turns.id"), c("iteration", I), c("draft_text", T),
         c("verdict"), c("overall_score", F), c("claim_findings", J),
         c("missing_evidence_queries", J), c("action_taken"),
         c("latency_ms", I), c("model_used", optional=True),
         c("created_at", D))
sa.Table("notes", m, c("id", pk=True),
         c("space_id", fk="research_spaces.id"),
         c("paper_id", fk="papers.id", optional=True), c("content", T),
         c("source"), c("chunk_id", fk="chunks.id", optional=True),
         c("anchor_quote", T, optional=True),
         c("anchor_start", I, optional=True), c("anchor_end", I, optional=True),
         c("color", optional=True), c("created_at", D), c("updated_at", D))
sa.Table("paper_profiles", m, c("id", pk=True),
         c("paper_id", fk="papers.id", unique=True),
         *[c(name, T, optional=True) for name in (
             "problem", "method", "dataset", "metrics", "results",
             "limitations", "future_work"
         )], c("generated_at", D), c("verified", B))
sa.Table("comparison_reports", m, c("id", pk=True),
         c("space_id", fk="research_spaces.id"),
         *[c(name, J) for name in (
             "paper_ids", "matrix", "commonalities", "contradictions", "gaps"
         )], c("confidence", F), c("generated_at", D))
sa.Table("space_memory", m, c("space_id", fk="research_spaces.id", pk=True),
         c("rolling_summary", T, optional=True), c("findings", J),
         c("open_questions", J), c("updated_at", D))

OPTIONAL_LEGACY = {
    "notes": {"chunk_id", "anchor_quote", "anchor_start", "anchor_end", "color"},
    "citations": {"paper_id", "section", "page", "quote"},
}


def validate_existing(bind):
    inspector = sa.inspect(bind)
    actual_tables = set(inspector.get_table_names()) - {"alembic_version"}
    expected_tables = set(m.tables)
    if actual_tables != expected_tables:
        raise RuntimeError(
            "Unrecognized legacy database tables (no stamp performed): "
            f"missing={sorted(expected_tables - actual_tables)}, "
            f"unexpected={sorted(actual_tables - expected_tables)}"
        )
    missing = {}
    for name, table in m.tables.items():
        present = {col["name"]: col for col in inspector.get_columns(name)}
        expected = {col.name: col for col in table.columns}
        allowed = OPTIONAL_LEGACY.get(name, set())
        absent = set(expected) - set(present)
        extra = set(present) - set(expected)
        if extra or absent - allowed:
            raise RuntimeError(f"Unrecognized {name} columns: missing={absent}, extra={extra}")
        missing[name] = absent
        for key, column in expected.items():
            if key not in present:
                continue
            actual = present[key]
            if (actual["type"]._type_affinity is not column.type._type_affinity
                    or bool(actual["nullable"]) != bool(column.nullable)
                    or bool(actual["primary_key"]) != bool(column.primary_key)):
                raise RuntimeError(f"Unrecognized column definition: {name}.{key}")
        actual_fks = {
            (tuple(fk["constrained_columns"]), fk["referred_table"],
             tuple(fk["referred_columns"])) for fk in inspector.get_foreign_keys(name)
        }
        expected_fks = {
            (tuple(col.name for col in fk.columns),
             fk.referred_table.name, tuple(el.column.name for el in fk.elements))
            for fk in table.foreign_key_constraints
            if not (name == "notes" and "chunk_id" in fk.column_keys)
        }
        optional_note_fk = (("chunk_id",), "chunks", ("id",))
        if (actual_fks - ({optional_note_fk} if name == "notes" else set())
                != expected_fks):
            raise RuntimeError(f"Unrecognized foreign keys on {name}")
        expected_unique = {
            tuple(sorted(col.name for col in constraint.columns))
            for constraint in table.constraints
            if isinstance(constraint, sa.UniqueConstraint)
        } | {
            tuple(sorted(col.name for col in idx.columns))
            for idx in table.indexes if idx.unique
        }
        actual_unique = {
            tuple(sorted(item["column_names"]))
            for item in inspector.get_unique_constraints(name)
        } | {
            tuple(sorted(item["column_names"]))
            for item in inspector.get_indexes(name) if item["unique"]
        }
        if actual_unique != expected_unique:
            raise RuntimeError(f"Unrecognized unique constraints on {name}")
    failed = bind.exec_driver_sql("PRAGMA integrity_check").scalar()
    if failed != "ok":
        raise RuntimeError(f"SQLite integrity check failed: {failed}")
    return missing


def upgrade():
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names()) - {"alembic_version"}
    if not tables:
        m.create_all(bind, checkfirst=False)
        return
    missing = validate_existing(bind)  # Validate everything BEFORE changing anything.
    for table_name, names in missing.items():
        for name in sorted(names):
            column = m.tables[table_name].c[name]
            op.add_column(table_name, sa.Column(name, column.type, nullable=True))


def downgrade():
    raise NotImplementedError("Restore the pre-migration SQLite backup instead.")
