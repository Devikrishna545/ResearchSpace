"""Add grounded-compare storage: evidence builds, source artifacts, typed facts, jobs, findings, corpus.

Additive only: existing tables are untouched except comparison_reports, which gains
report_kind (existing rows become 'legacy_profile'), report_json and job_id.

Revision ID: 0008_grounded_compare
Revises: 0007_chat_sessions
"""

from alembic import op
import sqlalchemy as sa

revision = "0008_grounded_compare"
down_revision = "0007_chat_sessions"
branch_labels = None
depends_on = None


def _ts(name, nullable=False):
    return sa.Column(name, sa.DateTime(timezone=True), nullable=nullable)


def upgrade():
    op.create_table(
        "paper_evidence_builds",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("paper_id", sa.String(), sa.ForeignKey("papers.id"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("is_current", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("parser_version", sa.String(), nullable=False),
        sa.Column("embed_model", sa.String(), nullable=True),
        sa.Column("text_source", sa.String(), nullable=False),
        sa.Column("pdf_sha256", sa.String(), nullable=True),
        sa.Column("page_count", sa.Integer(), nullable=False),
        sa.Column("scanned", sa.Boolean(), nullable=False),
        sa.Column("quality_flags", sa.JSON(), nullable=False),
        sa.Column("doc_metadata", sa.JSON(), nullable=False),
        _ts("created_at"),
        sa.UniqueConstraint("paper_id", "version", name="uq_evidence_build_paper_version"),
    )
    op.create_index("ix_paper_evidence_builds_paper_id", "paper_evidence_builds", ["paper_id"])

    op.create_table(
        "document_artifacts",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("build_id", sa.String(), sa.ForeignKey("paper_evidence_builds.id"), nullable=False),
        sa.Column("paper_id", sa.String(), sa.ForeignKey("papers.id"), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("page_start", sa.Integer(), nullable=True),
        sa.Column("page_end", sa.Integer(), nullable=True),
        sa.Column("section", sa.String(), nullable=True),
        sa.Column("label", sa.String(), nullable=True),
        sa.Column("caption", sa.Text(), nullable=True),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("cells", sa.JSON(), nullable=True),
        sa.Column("image_path", sa.String(), nullable=True),
        sa.Column("extraction_status", sa.String(), nullable=False),
        sa.Column("quality_flags", sa.JSON(), nullable=False),
        sa.Column("parser_version", sa.String(), nullable=False),
        sa.Column("content_hash", sa.String(), nullable=False),
        sa.Column("embedding_json", sa.JSON(), nullable=True),
        sa.Column("embed_model", sa.String(), nullable=True),
    )
    op.create_index("ix_document_artifacts_build_id", "document_artifacts", ["build_id"])
    op.create_index("ix_document_artifacts_paper_id", "document_artifacts", ["paper_id"])

    op.create_table(
        "evidence_facts",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("build_id", sa.String(), sa.ForeignKey("paper_evidence_builds.id"), nullable=False),
        sa.Column("paper_id", sa.String(), sa.ForeignKey("papers.id"), nullable=False),
        sa.Column("fact_type", sa.String(), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("normalized_value", sa.String(), nullable=False),
        sa.Column("attributes", sa.JSON(), nullable=False),
        sa.Column("source_ids", sa.JSON(), nullable=False),
        sa.Column("quote", sa.Text(), nullable=False),
        sa.Column("page", sa.Integer(), nullable=True),
        sa.Column("section", sa.String(), nullable=True),
        sa.Column("extraction_status", sa.String(), nullable=False),
        sa.Column("provenance_validation", sa.String(), nullable=False),
        sa.Column("type_validation", sa.String(), nullable=False),
        sa.Column("ownership_validation", sa.String(), nullable=False),
        sa.Column("dimension_validation", sa.String(), nullable=False),
        sa.Column("validation_notes", sa.JSON(), nullable=False),
        sa.Column("prompt_version", sa.String(), nullable=False),
        sa.Column("model_version", sa.String(), nullable=False),
        _ts("created_at"),
    )
    op.create_index("ix_evidence_facts_build_id", "evidence_facts", ["build_id"])
    op.create_index("ix_evidence_facts_paper_id", "evidence_facts", ["paper_id"])

    op.create_table(
        "llm_call_logs",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("job_id", sa.String(), nullable=True),
        sa.Column("paper_id", sa.String(), nullable=True),
        sa.Column("purpose", sa.String(), nullable=False),
        sa.Column("model", sa.String(), nullable=False),
        sa.Column("model_digest", sa.String(), nullable=True),
        sa.Column("prompt_version", sa.String(), nullable=False),
        sa.Column("seed", sa.Integer(), nullable=True),
        sa.Column("raw_output", sa.Text(), nullable=False),
        sa.Column("parse_status", sa.String(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        _ts("created_at"),
    )
    op.create_index("ix_llm_call_logs_job_id", "llm_call_logs", ["job_id"])
    op.create_index("ix_llm_call_logs_paper_id", "llm_call_logs", ["paper_id"])

    op.create_table(
        "analysis_jobs",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("owner_id", sa.String(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("space_id", sa.String(), sa.ForeignKey("research_spaces.id"), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("state", sa.String(), nullable=False),
        sa.Column("progress", sa.Float(), nullable=False),
        sa.Column("params", sa.JSON(), nullable=False),
        sa.Column("model_config_json", sa.JSON(), nullable=False),
        sa.Column("phase_log", sa.JSON(), nullable=False),
        sa.Column("warnings", sa.JSON(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("report_id", sa.String(), nullable=True),
        sa.Column("cancel_requested", sa.Boolean(), nullable=False),
        _ts("created_at"),
        _ts("updated_at"),
        _ts("finished_at", nullable=True),
    )
    op.create_index("ix_analysis_jobs_owner_id", "analysis_jobs", ["owner_id"])
    op.create_index("ix_analysis_jobs_space_id", "analysis_jobs", ["space_id"])

    with op.batch_alter_table("comparison_reports") as batch:
        batch.add_column(sa.Column("report_kind", sa.String(), nullable=False, server_default="legacy_profile"))
        batch.add_column(sa.Column("report_json", sa.JSON(), nullable=True))
        batch.add_column(sa.Column("job_id", sa.String(), nullable=True))

    op.create_table(
        "comparison_findings",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("report_id", sa.String(), sa.ForeignKey("comparison_reports.id"), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("dimension", sa.String(), nullable=False),
        sa.Column("statement", sa.Text(), nullable=False),
        sa.Column("paper_ids", sa.JSON(), nullable=False),
        sa.Column("fact_ids", sa.JSON(), nullable=False),
        sa.Column("source_ids", sa.JSON(), nullable=False),
        sa.Column("computed", sa.JSON(), nullable=False),
        sa.Column("evidence_status", sa.String(), nullable=False),
        sa.Column("verification_status", sa.String(), nullable=False),
        sa.Column("display_status", sa.String(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
    )
    op.create_index("ix_comparison_findings_report_id", "comparison_findings", ["report_id"])

    op.create_table(
        "literature_corpus_items",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("owner_id", sa.String(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("corpus_id", sa.String(), nullable=False),
        sa.Column("dedupe_key", sa.String(), nullable=False),
        sa.Column("paper_id", sa.String(), sa.ForeignKey("papers.id"), nullable=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("abstract", sa.Text(), nullable=True),
        sa.Column("year", sa.Integer(), nullable=True),
        sa.Column("doi", sa.String(), nullable=True),
        sa.Column("field", sa.String(), nullable=True),
        sa.Column("item_metadata", sa.JSON(), nullable=False),
        sa.Column("artifact_refs", sa.JSON(), nullable=False),
        sa.Column("permission", sa.String(), nullable=False),
        sa.Column("permission_note", sa.Text(), nullable=True),
        sa.Column("embedding_json", sa.JSON(), nullable=True),
        sa.Column("embed_model", sa.String(), nullable=True),
        _ts("added_at"),
        sa.UniqueConstraint("owner_id", "corpus_id", "dedupe_key", name="uq_corpus_item"),
    )
    op.create_index("ix_literature_corpus_items_owner_id", "literature_corpus_items", ["owner_id"])


def downgrade():
    raise NotImplementedError("Restore the pre-migration SQLite backup instead.")
