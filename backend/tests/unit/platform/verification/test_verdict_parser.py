import pytest
from app.core.exceptions import VerdictParseError
from app.platform.verification.schemas import VerdictType
from app.platform.verification.verdict_parser import VerdictParser
VALID='{"verdict":"APPROVED","overall_score":0.95,"claims":[],"missing_evidence_queries":[],"global_feedback":"","hallucination_flags":[]}'
def test_valid_json(): assert VerdictParser().parse(VALID).verdict==VerdictType.APPROVED
def test_repairable_json_fence_and_trailing_comma():
    raw='```json\n{"verdict":"REVISE","overall_score":0.4,"claims":[],}\n```'
    assert VerdictParser().parse(raw).verdict==VerdictType.REVISE
def test_malformed_json_raises():
    with pytest.raises(VerdictParseError): VerdictParser().parse('not json')
