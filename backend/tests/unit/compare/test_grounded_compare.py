import asyncio
import io
import json
import re

import httpx
import pytest
from fastapi.testclient import TestClient
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import Settings
from app.db.session import configure_sqlite_pragmas
from app.modules.compare.grounded import deterministic
from app.modules.compare.grounded import evidence
from app.modules.compare.grounded import extraction
from app.modules.compare.grounded import jobs
from app.modules.compare.grounded import llm as grounded_llm
from app.modules.compare.grounded import novelty
from app.modules.compare.grounded import numerics
from app.modules.compare.grounded import service
from app.modules.compare.grounded import normalizer as norm
from app.modules.compare.grounded.deterministic import DeterministicComparator, PaperEvidence
from app.modules.compare.grounded.fact_types import FACT_TYPES
from app.modules.compare.grounded.pdf_parsing import parse_pdf_bytes, text_units
from app.modules.compare.grounded.semantic import SemanticComparator
from app.modules.compare.grounded.tiers import tier_config
from app.modules.compare.grounded.validation import FactValidator, quote_in_source, value_in_source
from app.modules.compare.grounded.verifier import FindingVerifier, apply_display_policy
from app.db.models import Base
from app.modules.papers.orm.chunk import Chunk
from app.modules.compare.orm.comparison_report import ComparisonReport
from app.modules.compare.orm.grounded import AnalysisJob, ComparisonFinding, EvidenceFact, LLMCallLog, PaperEvidenceBuild
from app.modules.papers.orm.paper import Paper
from app.modules.spaces.orm.pin import Pin
from app.modules.spaces.orm.research_space import ResearchSpace
from app.modules.auth.orm.user import User
from app.modules.compare.schemas.grounded import (
    APPARENT_CONTRADICTION, COMMONALITY, DIRECT_CONTRADICTION, EVIDENCE_BACKED_INTERPRETATION, INSUFFICIENT_EVIDENCE,
    NOT_COMPARABLE, NUMERIC_COMPARISON, NUMERICALLY_VERIFIED, PARTIALLY_SUPPORTED, UNSUPPORTED, CompareJobRequest, Finding,
)
from app.modules.compare import service as compare_service
from app.modules.spaces import service as space_service


# ---------------------------------------------------------------- normalizer

def test_normalizer_accepts_bare_strings_and_plural_keys():
    result = norm.normalize('{"datasets":["Google News corpus","CBOW architecture"]}', ("facts", "dataset"))
    assert [i["value"] for i in result.items] == ["Google News corpus", "CBOW architecture"]
    assert result.status == norm.NORMALIZED


def test_normalizer_accepts_wrappers_labels_fences_and_trailing_commas():
    fenced = 'Here:\n```json\n{"output": {"findings": [{"value": "x",}]}}\n```'
    assert [i["value"] for i in norm.normalize(fenced, ("facts",)).items] == ["x"]
    labelled = norm.normalize('{"P1": ["a"], "P2": {"facts": [{"value": "b"}]}}', ("facts",), allow_paper_labels=True)
    assert [(i["value"], i["_paper_label"]) for i in labelled.items] == [("a", "P1"), ("b", "P2")]
    single = norm.normalize('{"value": "only", "quote": "q"}', ("facts",))
    assert single.items == [{"value": "only", "quote": "q"}]
    think = norm.normalize('<think>reasoning</think>{"facts": [], "not_found": true}', ("facts",))
    assert think.status == norm.NOT_FOUND and think.not_found


def test_normalizer_separates_parser_defects_from_model_failures():
    assert norm.normalize("not json at all", ("facts",)).status == norm.INVALID_JSON
    assert norm.normalize("{}", ("facts",)).status == norm.EMPTY
    assert norm.normalize('{"unexpected": {"deep": 1}}', ("facts",)).status == norm.PARSER_DEFECT
    assert norm.table_cells({"table": {"cells": [["a", "b"], ["1", 2]]}}) == [["a", "b"], ["1", "2"]]
    assert norm.table_cells([{"m": "acc", "v": "1"}, {"m": "f1", "v": "2"}]) == [["acc", "1"], ["f1", "2"]]


# ---------------------------------------------------------------- parsing

def make_pdf(pages: list[list[str]], table_page: int | None = None) -> bytes:
    writer = PdfWriter()
    for number, lines in enumerate(pages, start=1):
        page = writer.add_blank_page(width=612, height=792)
        font = writer._add_object(DictionaryObject({NameObject("/Type"): NameObject("/Font"), NameObject("/Subtype"): NameObject("/Type1"),
                                                    NameObject("/BaseFont"): NameObject("/Helvetica")}))
        page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})})
        ops = ["BT /F1 11 Tf 14 TL 72 740 Td"] + [f"({line}) Tj T*" for line in lines] + ["ET"]
        if number == table_page:
            # A ruled 3x2 table so deterministic table detection has real lines.
            ops += ["0.5 w", "72 400 m 372 400 l S", "72 380 m 372 380 l S", "72 360 m 372 360 l S", "72 340 m 372 340 l S",
                    "72 400 m 72 340 l S", "222 400 m 222 340 l S", "372 400 m 372 340 l S",
                    "BT /F1 10 Tf 80 386 Td (Method) Tj ET", "BT /F1 10 Tf 230 386 Td (Accuracy) Tj ET",
                    "BT /F1 10 Tf 80 366 Td (Proposed) Tj ET", "BT /F1 10 Tf 230 366 Td (91.3) Tj ET",
                    "BT /F1 10 Tf 80 346 Td (Baseline) Tj ET", "BT /F1 10 Tf 230 346 Td (88.0) Tj ET"]
        content = DecodedStreamObject()
        content.set_data("\n".join(ops).encode("latin-1"))
        page[NameObject("/Contents")] = writer._add_object(content)
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def test_pdf_parsing_keeps_pages_tables_captions_and_headings():
    data = make_pdf([
        ["1 Introduction", "We study word vectors.", "2 Method", "We train on the Google News corpus."],
        ["Results continue here without a heading.", "Table 1: Accuracy on analogy tasks"],
    ], table_page=2)
    parsed = parse_pdf_bytes(data)
    assert parsed.total_pages == 2
    assert parsed.tables and parsed.tables[0].page == 2
    assert ["Proposed", "91.3"] in parsed.tables[0].cells
    assert parsed.tables[0].label == "Table 1"
    units, flags = text_units(parsed.pages)
    assert {u["page"] for u in units} == {1, 2}
    assert all(len({u["page"]}) == 1 for u in units)
    # A heading carries onto the next page until a new heading appears.
    assert units[-1]["section"].startswith("Method")
    assert "no_headings_detected" not in flags


def test_text_units_are_paragraph_aligned_and_bounded():
    paragraph = " ".join(["word"] * 400) + "."
    units, _ = text_units(["\n\n".join([paragraph] * 5)])
    assert all(evidence_tokens(u["text"]) <= 1000 for u in units)
    assert len(units) >= 3


def evidence_tokens(text):
    from app.modules.compare.grounded.pdf_parsing import estimate_tokens
    return estimate_tokens(text)


# ---------------------------------------------------------------- validation and numerics

def test_provenance_checks_quote_and_value():
    source = "We train our model on the Google News corpus, which contains about 6B tokens.\nThe CBOW archi-\ntecture is used."
    assert quote_in_source("We train our model on the Google News corpus", source)[0]
    assert quote_in_source("The CBOW architecture is used.", source)[0]  # de-hyphenated
    assert not quote_in_source("We train on Wikipedia", source)[0]
    assert value_in_source("Google News corpus", "", source)[0]
    assert not value_in_source("7B tokens", "", source)[0]
    # PDF extraction that drops spaces still matches the same characters in order.
    merged = "Inordertomakeanyconcretestatementsabout the number of nonzero elements in X, it is necessary."
    assert quote_in_source("In order to make any concrete statements about the number of nonzero elements", merged) == (True, "exact_quote_ignoring_whitespace")
    assert value_in_source("concrete statements", "", merged)[0]


def test_numerics_percentage_points_vs_relative_change_and_scales():
    a, b = numerics.parse_number("91.3%"), numerics.parse_number("0.880")
    result = numerics.compare_values(a, b, "Accuracy")
    assert result["comparable"] and result["difference_percentage_points"] == pytest.approx(3.3)
    assert result["relative_change_percent"] == pytest.approx(3.75)
    assert result["better"] == "a"
    assert numerics.compare_values(numerics.parse_number("12.1"), numerics.parse_number("10.0"), "perplexity")["better"] == "b"
    assert not numerics.compare_counts(numerics.parse_number("6B tokens"), numerics.parse_number("100 sentences"))["comparable"]
    assert numerics.parse_number("1.2M").value == 1_200_000
    assert numerics.parse_number("91.3 ± 0.4").plus_minus == 0.4


def test_numerics_statistical_checks():
    good = numerics.check_statistics({"test": "t-test", "statistic": "2.5", "df": "30", "p_value": "0.018"})
    assert good["all_ok"] is True
    bad = numerics.check_statistics({"test": "t-test", "statistic": "2.5", "df": "30", "p_value": "0.30"})
    assert bad["all_ok"] is False
    assert numerics.check_statistics({"lower": "5", "upper": "3", "value": "4"})["all_ok"] is False
    assert numerics.check_statistics({"p_value": "p < 0.05", "threshold": "0.05"})["all_ok"] is True
    ok, reasons = numerics.result_conditions_match({"metric": "acc", "dataset": "SST-2"}, {"metric": "Accuracy", "dataset": "SST-2 dataset"}, "", "")
    assert ok, reasons
    ok, reasons = numerics.result_conditions_match({"metric": "acc", "dataset": "SST-2"}, {"metric": "Accuracy", "dataset": "IMDB"}, "", "")
    assert not ok and "different datasets" in reasons[0]


# ---------------------------------------------------------------- in-memory evidence helpers

class _Artifact:
    def __init__(self, id, paper_id, build_id, text, section="Method", kind="text", cells=None, page=1):
        self.id, self.paper_id, self.build_id, self.text, self.section = id, paper_id, build_id, text, section
        self.kind, self.cells, self.page_start, self.extraction_status = kind, cells, page, "parsed"
        self.ordinal, self.embedding_json, self.embed_model, self.image_path = 0, None, None, None
        self.label = self.caption = None
        self.quality_flags = []


class _Build:
    def __init__(self, id, paper_id):
        self.id, self.paper_id, self.version = id, paper_id, 1
        self.text_source, self.page_count, self.scanned, self.quality_flags = "local_pdf", 1, False, []
        self.parser_version, self.embed_model, self.doc_metadata = "v", "e", {}


def fact(paper, fact_type, value, source, *, status="validated", attributes=None, fid=None):
    return EvidenceFact(id=fid or f"{paper}-{fact_type}-{value}", build_id=f"b-{paper}", paper_id=paper, fact_type=fact_type,
                        value=value, normalized_value=value.lower(), attributes=attributes or {}, source_ids=[source],
                        quote=value, page=1, section="Method", extraction_status=status, provenance_validation="pass",
                        type_validation="pass", ownership_validation="pass", dimension_validation="pass", validation_notes=[],
                        prompt_version="p", model_version="m")


def paper(pid, label, facts, artifacts):
    return PaperEvidence(paper_id=pid, label=label, title=f"Paper {pid}", build=_Build(f"b-{pid}", pid),
                         artifacts_by_id={a.id: a for a in artifacts}, facts=facts)


def test_deterministic_commonality_requires_validated_facts_from_both_papers():
    a_src, b_src = _Artifact("a1", "pa", "b-pa", "Google News corpus"), _Artifact("b1", "pb", "b-pb", "Google News dataset")
    pa = paper("pa", "P1", [fact("pa", "dataset", "Google News corpus", "a1"),
                            fact("pa", "dataset", "CBOW architecture", "a1", status="rejected")], [a_src])
    pb = paper("pb", "P2", [fact("pb", "dataset", "Google News dataset", "b1"),
                            fact("pb", "dataset", "CBOW architecture", "b1", status="rejected")], [b_src])
    findings = DeterministicComparator([pa, pb]).compare_entities()
    commons = [f for f in findings if f.kind == COMMONALITY]
    assert len(commons) == 1 and "Google News" in commons[0].statement
    assert set(commons[0].paper_ids) == {"pa", "pb"}
    assert not any("CBOW" in f.statement for f in findings)
    assert any(f.kind == "insufficient_evidence" and f.dimension == "method" for f in findings)


def test_deterministic_results_need_matching_conditions_and_are_computed_in_code():
    table = _Artifact("t1", "pa", "b-pa", "Method | Accuracy", kind="table", cells=[["Method", "Accuracy"], ["Ours", "91.3"]])
    pa = paper("pa", "P1", [fact("pa", "result", "91.3", "t1", attributes={"metric": "Accuracy", "value": "91.3", "dataset": "SST-2"})], [table])
    pb = paper("pb", "P2", [fact("pb", "result", "88.0", "b1", attributes={"metric": "acc", "value": "88.0%", "dataset": "SST-2"}),
                            fact("pb", "result", "70.0", "b1", fid="pb-imdb", attributes={"metric": "accuracy", "value": "70.0%", "dataset": "IMDB"})],
               [_Artifact("b1", "pb", "b-pb", "88.0 70.0")])
    findings = DeterministicComparator([pa, pb]).compare_numerics()
    numeric = [f for f in findings if f.kind == NUMERIC_COMPARISON]
    assert len(numeric) == 1 and numeric[0].evidence_status == NUMERICALLY_VERIFIED
    assert numeric[0].computed["difference_percentage_points"] == pytest.approx(3.3)
    assert numeric[0].computed["table_confirmed"]["a"] is True
    not_comparable = [f for f in findings if f.kind == NOT_COMPARABLE]
    assert len(not_comparable) == 1 and "different datasets" in not_comparable[0].statement


# ---------------------------------------------------------------- fake local model

class FakeClient:
    """Answers each grounded prompt family deterministically, like a fixed-seed local model."""

    def __init__(self, gate: asyncio.Event | None = None, verify_verdict="supported"):
        self.calls = []
        self.gate = gate
        self.verify_verdict = verify_verdict

    async def model_digests(self):
        return {"qwen3:8b": "sha256:abc123def4567890", "embeddinggemma:300m-qat-q4_0": "sha256:e"}

    async def version(self):
        return "0.34.4"

    async def embed(self, texts, model):
        return [[1.0 + (len(t) % 5), 1.0, 0.5 + ("dataset" in t.lower())] for t in texts]

    async def chat(self, messages, model, temperature=0.0, json_format=False, **kwargs):
        if self.gate is not None:
            await self.gate.wait()
        system, user = messages[0]["content"], messages[1]["content"]
        self.calls.append((system[:40], kwargs.get("seed"), kwargs.get("schema") is not None))
        if "extract typed facts" in system:
            return self._extract(user)
        if "validate the entity type" in system:
            ids = re.findall(r"Item id: (\S+)\nCandidate value: (.+)", user)
            return json.dumps({"results": [{"id": i, "answer": "no" if "CBOW" in v else "yes", "reason": "r"} for i, v in ids]})
        if "check ownership" in system:
            ids = re.findall(r"Item id: (\S+)", user)
            return json.dumps({"results": [{"id": i, "belongs_to_this_paper": "yes", "answers_dimension": "yes", "reason": "r"} for i in ids]})
        if "compare research papers on ONE dimension" in system:
            ids = re.findall(r"fact_id: (\S+)", user)
            if ids:
                return json.dumps({"relations": [{"relation": "commonality_candidate", "statement": "P1 and P2 both note limited data.", "fact_ids": ids}]})
            return '{"relations": []}'
        if "verify ONE candidate finding" in system:
            return json.dumps({"verdict": self.verify_verdict, "reason": "checked"})
        if "CANDIDATE research gaps" in system:
            ids = re.findall(r"fact_id: (\S+) \| limitation", user)
            if len(ids) >= 2:
                return json.dumps({"gaps": [{"description": "Neither paper evaluates beyond English news text.", "category": "generalizability_gap", "fact_ids": ids}]})
            return '{"gaps": [], "no_gaps_reason": "none"}'
        if "already addressed by retrieved" in system:
            return json.dumps({"verdict": "not_addressed", "item_ids": [], "reason": "no match"})
        return "{}"

    def _extract(self, user):
        fact_type = re.search(r"Requested fact type: (\w+)", user).group(1).lower()
        sources = re.findall(r"\[source_id: (\S+) \|[^\]]*\]\n(.+)", user)
        facts = []
        for source_id, text in sources:
            if fact_type == "dataset":
                for name in ("Google News corpus", "CBOW architecture"):
                    if name in text:
                        sentence = next(s for s in re.split(r"(?<=\.)\s+", text) if name in s)
                        facts.append({"value": name, "source_id": source_id, "quote": sentence, "owner": "this_paper"})
            if fact_type == "limitation" and "only English" in text:
                sentence = next(s for s in re.split(r"(?<=\.)\s+", text) if "only English" in s)
                facts.append({"value": sentence.rstrip("."), "source_id": source_id, "quote": sentence, "owner": "this_paper"})
        # A bare-string list in a plural key: the shape the old parser mis-scored as a model failure.
        if fact_type == "method":
            return '{"methods": []}'
        return json.dumps({"facts": facts, "not_found": not facts})


@pytest.fixture
async def db(tmp_path, monkeypatch):
    engine = configure_sqlite_pragmas(create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'grounded.db'}", future=True))
    session_local = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with session_local() as session:
        session.add(User(id="test-owner", email="owner@example.com", is_admin=False))
        await session.commit()
    for module in (evidence, extraction, jobs, grounded_llm, novelty, service, compare_service, space_service):
        monkeypatch.setattr(module, "SessionLocal", session_local, raising=False)
    monkeypatch.setattr("app.modules.papers.ingestion.upload.get_settings", lambda: Settings(upload_dir=tmp_path / "uploads"))
    jobs._tasks.clear()
    jobs._cancelled.clear()
    yield session_local
    await engine.dispose()


async def seed(db):
    texts = {
        "pa": "We train our model on the Google News corpus. The CBOW architecture is used. We evaluate only English news text.",
        "pb": "Our experiments use the Google News corpus for evaluation. We consider only English sentences in this study.",
    }
    async with db() as session:
        session.add(ResearchSpace(id="s1", user_id="test-owner", name="S"))
        for pid, text in texts.items():
            session.add(Paper(id=pid, owner_id="test-owner", title=f"Paper {pid}", authors=[], abstract="abs", raw_payload={}, content_hash=f"h-{pid}"))
        await session.flush()
        for pid, text in texts.items():
            session.add(Pin(id=f"pin-{pid}", space_id="s1", paper_id=pid))
            session.add(Chunk(id=f"{pid}-0", paper_id=pid, ordinal=0, section="Method", page=1, text=text, embedding_json=[1.0]))
        await session.commit()


def service_for(client, **settings):
    return jobs.CompareJobService(Settings(**settings), client=client)


async def wait_for(job_service, job_id, states=("completed", "completed_with_warnings", "failed", "cancelled")):
    for _ in range(400):
        job = await job_service.get(job_id)
        if job.state in states:
            return job
        await asyncio.sleep(0.02)
    raise AssertionError(f"job stuck in {job.state}")


async def test_grounded_job_end_to_end_suppresses_type_errors_and_links_evidence(db):
    await seed(db)
    client = FakeClient()
    job_service = service_for(client)
    started = await job_service.start("s1", CompareJobRequest(paper_ids=["pb", "pa"]))
    assert started.state == "queued" and "Candidate gaps" in started.pending_sections
    job = await wait_for(job_service, started.id)
    assert job.state == "completed_with_warnings", (job.error, job.warnings)
    assert job.progress == 1.0 and job.report_id
    phases = [entry["phase"] for entry in job.phase_log]
    for phase in ("parsing", "indexing", "extracting_facts", "validating_facts", "comparing", "computing_numerics",
                  "verifying_findings", "identifying_candidate_gaps", "rendering_report"):
        assert phase in phases
    assert all(seed_value == 42 for _, seed_value, _ in client.calls)

    report = await compare_service.CompareService(Settings()).get_report(job.report_id)
    assert report["report_kind"] == "grounded"
    commons = report["sections"]["commonalities"]
    dataset_common = [f for f in commons if f["dimension"] == "dataset"]
    assert len(dataset_common) == 1 and "Google News" in dataset_common[0]["statement"]
    assert all("CBOW" not in f["statement"] for section in report["sections"].values() for f in section)
    # The CBOW type error is kept only in the audit record.
    audit = report["audit_record"]["pa"]
    assert any(f["value"] == "CBOW architecture" and f["type_validation"] == "fail" for f in audit)
    # Every shown finding resolves to source spans in the appendix.
    for section in report["sections"].values():
        for finding in section:
            assert finding["source_ids"] and all(s in report["evidence_appendix"] for s in finding["source_ids"])
    semantic = [f for f in commons if f["basis"] == "interpretation"]
    assert semantic and semantic[0]["evidence_status"] == EVIDENCE_BACKED_INTERPRETATION
    gaps = report["sections"]["candidate_gaps"]
    assert gaps and gaps[0]["coverage_note"].startswith("Based only on the selected papers")
    assert gaps[0]["novelty"]["label"] == "novelty_not_assessed"
    table = {row["dimension"]: row for row in report["deterministic_table"]}
    assert table["metric"]["cells"]["P1"]["status"] == "insufficient_evidence"
    assert report["model_metadata"]["model_digests"]["qwen3:8b"].startswith("sha256")

    diagnostics = await service.job_diagnostics(job.id)
    assert diagnostics["parser_defects"] == 0
    async with db() as session:
        statuses = (await session.execute(select(LLMCallLog.purpose, LLMCallLog.parse_status))).all()
        # {"methods": []} is a valid "nothing found" shape, never blamed on the model or the parser.
        assert ("extract:method", "not_found") in statuses
        assert not any(status in {"parser_defect", "model_empty"} for purpose, status in statuses if purpose.startswith("extract"))
        assert await session.scalar(select(ComparisonFinding.id).where(ComparisonFinding.report_id == job.report_id).limit(1))

    summaries = await compare_service.CompareService(Settings()).list_reports("s1")
    assert summaries[0].report_kind == "grounded"

    # A second run reuses the evidence ledger and the unchanged report; no extraction calls.
    calls_before = len(client.calls)
    again = await wait_for(job_service, (await job_service.start("s1", CompareJobRequest(paper_ids=["pa", "pb"]))).id)
    assert again.report_id == job.report_id and len(client.calls) == calls_before


async def test_unsupported_interpretations_are_withheld(db):
    await seed(db)
    job_service = service_for(FakeClient(verify_verdict="unsupported"))
    job = await wait_for(job_service, (await job_service.start("s1", CompareJobRequest(paper_ids=["pa", "pb"]))).id)
    report = await compare_service.CompareService(Settings()).get_report(job.report_id)
    assert all(f["basis"] != "interpretation" for s in report["sections"].values() for f in s)
    assert report["withheld_count"] >= 1
    assert report["candidate_gaps_empty_reason"]


async def test_refresh_rebuilds_evidence_and_does_not_reuse_saved_report(db):
    await seed(db)
    client = FakeClient()
    job_service = service_for(client)
    first = await wait_for(job_service, (await job_service.start("s1", CompareJobRequest(paper_ids=["pa", "pb"]))).id)
    calls_before = len(client.calls)
    refreshed = await wait_for(job_service, (await job_service.start(
        "s1", CompareJobRequest(paper_ids=["pa", "pb"], refresh=True),
    )).id)
    assert refreshed.state in {"completed", "completed_with_warnings"}, refreshed.error
    assert refreshed.report_id != first.report_id
    assert len(client.calls) > calls_before
    old = await compare_service.CompareService(Settings()).get_report(first.report_id)
    new = await compare_service.CompareService(Settings()).get_report(refreshed.report_id)
    assert old["stale_paper_ids"] == ["pa", "pb"]
    assert new["stale_paper_ids"] == []
    assert all(new["builds"][pid] != old["builds"][pid] for pid in ("pa", "pb"))


async def test_grounded_timeout_keeps_pinned_model_and_records_model_error():
    class TimedOutClient:
        def __init__(self):
            self.calls = []

        async def chat(self, messages, model, **kwargs):
            self.calls.append((model, kwargs))
            raise TimeoutError("local model deadline exceeded")

    client = TimedOutClient()
    tier = tier_config(Settings())
    gateway = grounded_llm.GroundedLLM(client, tier, timeout_s=1.25, persist_logs=False)
    result, model = await gateway.call(
        purpose="migration-timeout", prompt_version="unchanged", system="test", user="test",
    )
    assert model == tier.text_model
    assert result.status == norm.MODEL_ERROR
    assert result.notes == ["TimeoutError: local model deadline exceeded"]
    assert len(client.calls) == 1
    assert client.calls[0][1]["timeout"] == 1.25
    assert client.calls[0][1]["seed"] == tier.seed
    assert client.calls[0][1]["temperature"] == 0.0


async def test_compare_routes_preserve_auth_validation_jobs_reports_and_ownership(db, monkeypatch):
    from app.core import auth, ownership
    from app.main import create_app
    from app.modules.compare import grounded_api

    await seed(db)
    job_service = service_for(FakeClient())
    monkeypatch.setattr(ownership, "SessionLocal", db)
    monkeypatch.setattr(grounded_api, "CompareJobService", lambda settings: job_service)
    api = create_app()
    user_id = "test-owner"

    async def authenticated():
        token = auth._active_user_id.set(user_id)
        try:
            yield User(id=user_id, email=f"{user_id}@example.com", is_admin=False)
        finally:
            auth._active_user_id.reset(token)

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=api), base_url="http://test") as client:
        assert (await client.get("/v1/spaces/s1/compare-jobs")).status_code == 401
        api.dependency_overrides[auth.current_user] = authenticated
        for payload in ({"paper_ids": []}, {"paper_ids": ["pa", "pa"]},
                        {"paper_ids": ["pa", "pb"], "tier": "invalid"}):
            assert (await client.post("/v1/spaces/s1/compare-jobs", json=payload)).status_code == 422
        missing = await client.post("/v1/spaces/s1/compare-jobs", json={"paper_ids": ["pa", "missing"]})
        assert missing.status_code == 404 and missing.json() == {"detail": "Resource not found"}
        started = await client.post("/v1/spaces/s1/compare-jobs", json={"paper_ids": ["pb", "pa"]})
        assert started.status_code == 202 and started.json()["state"] == "queued"
        job = await wait_for(job_service, started.json()["id"])
        status = await client.get(f"/v1/compare-jobs/{job.id}")
        assert status.status_code == 200 and status.json()["report_id"] == job.report_id
        report = await client.get(f"/v1/comparisons/{job.report_id}")
        assert report.status_code == 200 and report.json()["report_kind"] == "grounded"
        user_id = "another-owner"
        for path in ("/v1/spaces/s1/compare-jobs", f"/v1/compare-jobs/{job.id}",
                     f"/v1/comparisons/{job.report_id}", "/v1/papers/pa/evidence"):
            assert (await client.get(path)).status_code == 404


async def test_job_cancellation_and_interrupted_jobs(db):
    await seed(db)
    gate = asyncio.Event()
    job_service = service_for(FakeClient(gate=gate))
    started = await job_service.start("s1", CompareJobRequest(paper_ids=["pa", "pb"]))
    for _ in range(100):
        if (await job_service.get(started.id)).state != "queued":
            break
        await asyncio.sleep(0.02)
    cancelled = await job_service.cancel(started.id)
    assert cancelled.cancel_requested
    job = await wait_for(job_service, started.id)
    assert job.state == "cancelled"
    gate.set()
    async with db() as session:
        session.add(AnalysisJob(id="orphan", owner_id="test-owner", space_id="s1", kind="compare", state="comparing", progress=0.5,
                                params={}, model_config_json={}, phase_log=[], warnings=[], cancel_requested=False))
        await session.commit()
    orphan = await job_service.get("orphan")
    assert orphan.state == "failed" and "reused" in orphan.error


async def test_rebuild_invalidates_dependent_reports_and_space_delete_cleans_up(db):
    await seed(db)
    job_service = service_for(FakeClient())
    job = await wait_for(job_service, (await job_service.start("s1", CompareJobRequest(paper_ids=["pa", "pb"]))).id)
    rebuild = await wait_for(job_service, (await job_service.start_rebuild("pa")).id)
    assert rebuild.state in {"completed", "completed_with_warnings"}, rebuild.error
    async with db() as session:
        versions = (await session.execute(select(PaperEvidenceBuild.version, PaperEvidenceBuild.is_current)
                                          .where(PaperEvidenceBuild.paper_id == "pa").order_by(PaperEvidenceBuild.version))).all()
    assert versions == [(1, False), (2, True)]
    report = await compare_service.CompareService(Settings()).get_report(job.report_id)
    assert report["stale_paper_ids"] == ["pa"] and report["stale_warning"]
    ledger = await service.evidence_ledger(Settings(), "pa")
    assert ledger["build"]["version"] == 2 and ledger["stale_reason"] is None
    assert any(f["value"] == "Google News corpus" for f in ledger["facts"])
    assert "derived_from_ingest_chunks" in ledger["build"]["quality_flags"]
    await space_service.SpaceService().delete("s1")
    async with db() as session:
        assert not (await session.execute(select(ComparisonFinding.id))).first()
        assert not (await session.execute(select(AnalysisJob.id))).first()


async def test_novelty_requires_corpus_coverage_and_never_claims_proof(db):
    await seed(db)
    client = FakeClient()
    corpus = novelty.CorpusService(client.embed, "embeddinggemma:300m-qat-q4_0")
    await corpus.add_metadata("default", [{"title": f"Related {i}", "abstract": "text", "year": 2000 + i, "permission": "metadata_only"} for i in range(3)])
    job_service = service_for(client)
    job = await wait_for(job_service, (await job_service.start("s1", CompareJobRequest(paper_ids=["pa", "pb"], check_novelty=True))).id)
    report = await compare_service.CompareService(Settings()).get_report(job.report_id)
    assert report["novelty"]["status"] == "insufficient_literature_coverage"
    assert report["novelty"]["coverage"]["size"] == 3 and report["novelty"]["coverage"]["search_limitations"]
    assert all(g["novelty"]["label"] == "insufficient_literature_coverage" for g in report["sections"]["candidate_gaps"])
    await corpus.add_metadata("default", [{"title": f"More {i}", "abstract": "t", "permission": "metadata_only"} for i in range(20)])
    job = await wait_for(job_service, (await job_service.start("s1", CompareJobRequest(paper_ids=["pa", "pb"], check_novelty=True, refresh=True))).id)
    report = await compare_service.CompareService(Settings()).get_report(job.report_id)
    labels = {g["novelty"]["label"] for g in report["sections"]["candidate_gaps"]}
    assert labels == {"possibly_novel_in_available_corpus"}
    assert "proven novel" not in json.dumps(report, default=str).lower()


# ---------------------------------------------------------------- policies

class _LLM:
    def __init__(self, reply):
        self.reply = reply
        self.tier = tier_config(Settings())
        self.stats = {}

    async def call(self, **kwargs):
        return norm.normalize_object(self.reply) if kwargs.get("single_object") else norm.normalize(self.reply, kwargs.get("list_names", ())), "m"


def _two_papers():
    a = paper("pa", "P1", [fact("pa", "limitation", "small data", "a1"), fact("pa", "dataset", "X", "a1")], [_Artifact("a1", "pa", "b-pa", "small data X")])
    b = paper("pb", "P2", [fact("pb", "limitation", "large data", "b1")], [_Artifact("b1", "pb", "b-pb", "large data")])
    return a, b


async def test_semantic_policy_drops_one_sided_commonality_and_downgrades_contradictions():
    a, b = _two_papers()
    reply = json.dumps({"relations": [
        {"relation": "commonality_candidate", "statement": "Both use small data.", "fact_ids": ["pa-limitation-small data"]},
        {"relation": "direct_contradiction_candidate", "statement": "P1 says small, P2 says large.",
         "fact_ids": ["pa-limitation-small data", "pb-limitation-large data"]},
    ]})
    findings = await SemanticComparator(_LLM(reply))._dimension("limitation", [a, b], comparable_pairs=set())
    assert [f.kind for f in findings] == [APPARENT_CONTRADICTION]
    assert "Downgraded" in findings[0].reason
    kept = await SemanticComparator(_LLM(reply))._dimension("limitation", [a, b], comparable_pairs={frozenset(("pa", "pb"))})
    assert [f.kind for f in kept] == [DIRECT_CONTRADICTION]


async def test_verifier_policy_and_display_statuses():
    a, b = _two_papers()
    finding = Finding(finding_id="f", kind=COMMONALITY, dimension="limitation", statement="Both are limited.",
                      paper_ids=["pa", "pb"], fact_ids=["pa-limitation-small data"], basis="interpretation")
    checked = await FindingVerifier(_LLM('{"verdict": "supported", "reason": ""}'), [a, b]).verify(finding)
    assert checked.evidence_status == INSUFFICIENT_EVIDENCE and apply_display_policy(checked).display_status == "withheld"
    partial = Finding(finding_id="g", kind=COMMONALITY, dimension="limitation", statement="Both are limited.", paper_ids=["pa", "pb"],
                      fact_ids=["pa-limitation-small data", "pb-limitation-large data"], basis="interpretation")
    checked = await FindingVerifier(_LLM('{"verdict": "partially_supported", "reason": "r", "unsupported_parts": "both"}'), [a, b]).verify(partial)
    assert checked.evidence_status == PARTIALLY_SUPPORTED and apply_display_policy(checked).display_status == "shown_with_caveat"
    partial.evidence_status = "pending"
    checked = await FindingVerifier(_LLM('{"verdict": "unsupported", "reason": "no"}'), [a, b]).verify(partial)
    assert checked.evidence_status == UNSUPPORTED and apply_display_policy(checked).display_status == "withheld"
    weak = Finding(finding_id="h", kind=COMMONALITY, dimension="x", statement="s", evidence_status=EVIDENCE_BACKED_INTERPRETATION, basis="interpretation")
    assert apply_display_policy(weak, final_authority=False).display_status == "shown_with_caveat"


async def test_validator_rejects_related_work_and_uncertain_is_not_validated():
    art = _Artifact("r1", "pa", "b-pa", "Prior work used ImageNet for training.", section="Related Work")
    f = fact("pa", "dataset", "ImageNet", "r1", status="candidate")
    f.quote, f.provenance_validation, f.type_validation, f.ownership_validation, f.dimension_validation = (
        "Prior work used ImageNet for training.", "pending", "pending", "pending", "pending")
    await FactValidator(_LLM('{"results": []}')).validate([f], {"r1": art}, FACT_TYPES["dataset"], "Paper")
    assert f.ownership_validation == "fail" and f.extraction_status == "rejected"
    g = fact("pa", "dataset", "COCO", "c1", status="candidate")
    g.quote, g.provenance_validation, g.type_validation, g.ownership_validation, g.dimension_validation = (
        "We use COCO.", "pending", "pending", "pending", "pending")
    await FactValidator(_LLM('{"results": []}')).validate([g], {"c1": _Artifact("c1", "pa", "b-pa", "We use COCO.")}, FACT_TYPES["dataset"], "Paper")
    assert g.type_validation == "uncertain" and g.extraction_status == "uncertain"


def test_tiers_and_routes():
    settings = Settings()
    assert tier_config(settings).text_model == "qwen3:8b"
    assert tier_config(settings, "weak").final_evidence_authority is False
    assert tier_config(settings, "deep").think is True
    from app.main import create_app
    paths = TestClient(create_app()).get("/openapi.json").json()["paths"]
    for path in ("/v1/spaces/{space_id}/compare-jobs", "/v1/compare-jobs/{job_id}", "/v1/compare-jobs/{job_id}/cancel",
                 "/v1/comparisons/{report_id}", "/v1/papers/{paper_id}/evidence/rebuild", "/v1/papers/{paper_id}/evidence",
                 "/v1/corpus", "/v1/grounded/tiers", "/v1/evidence/artifacts/{artifact_id}/image"):
        assert path in paths

# ---------------------------------------------------------------- review regressions

async def test_unverifiable_numeric_attributes_are_dropped_before_comparison():
    art = _Artifact("r1", "pa", "b-pa", "Our model reaches 91.3% accuracy on SST-2.", section="Results")
    f = fact("pa", "result", "91.3%", "r1", status="candidate", attributes={"metric": "accuracy", "value": "93.1", "dataset": "SST-2"})
    f.quote, f.provenance_validation, f.type_validation, f.ownership_validation, f.dimension_validation = (
        "Our model reaches 91.3% accuracy on SST-2.", "pending", "pending", "pending", "pending")
    FactValidator(_LLM("{}")).check_provenance(f, {"r1": art})
    assert f.provenance_validation == "pass"
    assert f.attributes == {"metric": "accuracy", "dataset": "SST-2"}
    assert "attribute_dropped:value" in f.validation_notes


async def test_validator_model_failure_keeps_fact_retryable():
    g = fact("pa", "dataset", "COCO", "c1", status="candidate")
    g.quote, g.provenance_validation, g.type_validation, g.ownership_validation, g.dimension_validation = (
        "We use COCO.", "pending", "pending", "pending", "pending")
    await FactValidator(_LLM("not json")).validate([g], {"c1": _Artifact("c1", "pa", "b-pa", "We use COCO.")}, FACT_TYPES["dataset"], "Paper")
    assert g.extraction_status == "candidate" and any(n.startswith("type_validator_failed") for n in g.validation_notes)


async def test_statement_covering_uncited_paper_is_rejected():
    a, b = _two_papers()
    c = paper("pc", "P3", [fact("pc", "limitation", "tiny data", "c1")], [_Artifact("c1", "pc", "b-pc", "tiny data")])
    reply = json.dumps({"relations": [{"relation": "commonality_candidate", "statement": "All papers acknowledge limited data.",
                                       "fact_ids": ["pa-limitation-small data", "pb-limitation-large data"]}]})
    findings = await SemanticComparator(_LLM(reply))._dimension("limitation", [a, b], set(), all_papers=[a, b, c])
    assert findings[0].computed["required_papers"] == ["pa", "pb", "pc"]
    checked = await FindingVerifier(_LLM('{"verdict": "supported", "reason": ""}'), [a, b, c]).verify(findings[0])
    assert checked.evidence_status == INSUFFICIENT_EVIDENCE and "cites no evidence" in checked.reason


def test_weak_tier_caveats_even_direct_findings():
    direct = Finding(finding_id="d", kind=COMMONALITY, dimension="dataset", statement="s", evidence_status="DIRECTLY_EVIDENCED", basis="direct_evidence")
    assert apply_display_policy(direct, final_authority=False).display_status == "shown_with_caveat"


async def test_deleting_space_stops_its_running_job(db):
    await seed(db)
    gate = asyncio.Event()
    job_service = service_for(FakeClient(gate=gate))
    started = await job_service.start("s1", CompareJobRequest(paper_ids=["pa", "pb"]))
    for _ in range(100):
        if (await job_service.get(started.id)).state != "queued":
            break
        await asyncio.sleep(0.02)
    task = jobs._tasks[started.id]
    await space_service.SpaceService().delete("s1")
    await asyncio.wait_for(asyncio.shield(task), timeout=5) if not task.done() else None
    assert task.done() and started.id not in jobs._tasks
    gate.set()


def test_truncated_output_keeps_only_complete_items():
    raw = '{"facts": [{"value": "a", "quote": "q1"}, {"value": "b", "quote": "q2"}, {"value": "c", "quo'
    result = norm.normalize(raw, ("facts",))
    assert [i["value"] for i in result.items] == ["a", "b"]
    assert "truncated_output_salvaged" in result.notes and result.status == norm.NORMALIZED


def test_entity_matching_handles_spacing_and_metric_wording():
    from app.modules.compare.grounded.deterministic import entity_keys
    assert entity_keys("Gigaword 5") & entity_keys("Gigaword5")
    assert entity_keys("percent accuracy", "metric") & entity_keys("Accuracy", "metric")
    assert not entity_keys("Accuracy", "metric") & entity_keys("F1 score", "metric")
    assert numerics.canonical_metric("Accuracy[%]") == "accuracy"
