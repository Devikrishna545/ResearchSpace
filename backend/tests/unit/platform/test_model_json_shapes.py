import json

import pytest

from app.modules.chat.agents.memory_agent import MemoryAgent
from app.modules.notes.agent import NotesAgent
from app.core.exceptions import VerdictParseError
from app.modules.compare.grounded import normalizer as norm
from app.platform.retrieval.query_rewriter import QueryRewriter
from app.platform.verification.schemas import ClaimStatus, VerdictType
from app.platform.llm.model_json import extract_json, field, list_items
from app.platform.verification.verdict_parser import VerdictParser


def test_verbatim_captured_flat_compare_shape_from_failed_real_map_call():
    # The P1 wording and chunk ID are from the saved 2026-09-26 raw response
    # excerpt; this top-level paper-label shape was once mis-scored as a model failure.
    raw = json.dumps({
        "P1": {
            "text": "global log-bilinear regression model",
            "chunk_id": "4509d60f-b6be-4af8-b936-da4f592c2810-1",
            "quote": "The result is a new global log-bilinear regression model that combines the advantages of the two major model families in the literature: global matrix factorization and local context window methods.",
        },
        "P2": {"text": "continuous vector representations", "chunk_id": "p2-c1"},
        "commonality": {"text": "Both discuss vector representations.", "paper_labels": ["P1", "P2"]},
    })
    result = norm.normalize(raw, ("facts",), text_key="text", allow_paper_labels=True)
    assert result.usable and result.status == norm.NORMALIZED
    assert [(i["text"], i["_paper_label"]) for i in result.items] == [
        ("global log-bilinear regression model", "P1"), ("continuous vector representations", "P2")]


@pytest.mark.parametrize("raw", [
    '["Missing baseline"]',
    '{"GAP":"Missing baseline"}',
    '{"OUTPUT":{"ITEMS":["Missing baseline"]}}',
    '{"FINDINGS":[{"DESCRIPTION":"Missing baseline","CATEGORY":"scope"}]}',
])
def test_gap_accepts_bare_string_single_and_wrapped_items(raw):
    result = norm.normalize(raw, ("gaps",), text_key="description")
    assert norm.get_key(result.items[0], "description") == "Missing baseline"


def test_verbatim_captured_dataset_shape_is_valid_data_not_a_parse_failure():
    # Actual JSON shape from the controlled word2vec extraction; no dataset
    # classification is inferred by this shape-only helper.
    raw = '{"datasets": ["Google News corpus", "CBOW architecture"]}'
    assert list_items(extract_json(raw), "datasets", aliases=("dataset",), text_key="name") == [
        {"name": "Google News corpus"}, {"name": "CBOW architecture"},
    ]
    assert list_items({"DATASET": {"NAME": "Google News corpus"}}, "datasets",
                      aliases=("dataset",), text_key="name") == [{"NAME": "Google News corpus"}]
    assert field({"NAME": "Google News corpus"}, "name") == "Google News corpus"


def test_notes_contributions_string_and_objects_and_case_insensitive():
    agent = NotesAgent()
    note = agent._parse('{"SUMMARY":"Paper summary","KEY_CONTRIBUTIONS":["first",{"name":"second"}],'
                        '"METHODOLOGY":"method","RESULTS":"good"}')
    assert note["key_contributions"] == ["first", "second"]
    assert note["summary"] == "Paper summary" and note["methodology"] == "method"
    assert note["limitations"] == ""


def test_memory_findings_and_questions_preserve_supplied_values():
    result = MemoryAgent()._parse_findings('{"FINDING":"observed","OPEN_QUESTIONS":[{"question":"Next?"}]}')
    assert result == {"findings": ["observed"], "open_questions": ["Next?"]}


def test_verdict_aliases_and_explicit_claim_status_are_not_fabricated():
    verdict = VerdictParser().parse('```json\n{"OUTPUT":{"VeRdIcT":"approved","OvErAlL_ScOrE":0.95,'
                                    '"CLAIM":{"CLAIM_ID":"c1","STATUS":"supported","CLAIM_TEXT":"Fact"}}}\n```')
    assert verdict.verdict == VerdictType.APPROVED
    assert verdict.claims[0].claim_id == "c1"
    assert verdict.claims[0].status == ClaimStatus.SUPPORTED
    with pytest.raises(VerdictParseError):
        VerdictParser().parse('{"verdict":"APPROVED","overall_score":0.95,"claims":["unsupported assertion"]}')
    with pytest.raises(VerdictParseError):
        VerdictParser().parse('{"verdict":"APPROVED","overall_score":0.95,'
                              '"claims":[{"claim_id":"c1","claim_text":"Fact"}]}')


def test_json_rewriter_explicit_question_only_and_plain_text_preserved():
    rewriter = QueryRewriter()
    assert rewriter._clean('{"QUESTION":"What datasets were used?"}') == "What datasets were used?"
    assert rewriter._clean('```json\n{"rewritten":"What happened?"}\n```') == "What happened?"
    assert rewriter._clean("What happened?") == "What happened?"
    assert rewriter._clean('{"data":["not a question"]}') == ""


def test_existing_json_fences_trailing_commas_and_missing_values():
    assert extract_json('Response:\n```json\n{"data":["x",]}\n```') == {"data": ["x"]}
    assert list_items({"gaps": [{"category": "missing"}]}, "gaps", text_key="description") == [
        {"category": "missing"}
    ]
    missing = norm.normalize('{"gaps":[{"category":"missing"}]}', ("gaps",), text_key="description")
    assert norm.get_key(missing.items[0], "description") is None
    assert norm.normalize('{"gaps":[],"not_found":true}', ("gaps",)).status == norm.NOT_FOUND


def test_generic_wrappers_do_not_reclassify_unrelated_sibling_fields():
    assert NotesAgent()._parse('{"summary":"Summary","results":"An observed result"}')["key_contributions"] == []
    assert MemoryAgent()._parse_findings('{"open_questions":["Question?"],"results":["Not a finding"]}') == {
        "findings": [], "open_questions": ["Question?"],
    }
    # A named key wins over the generic "results" wrapper.
    assert norm.normalize('{"relations":[],"results":"Paper-specific result"}', ("relations",)).items == []
