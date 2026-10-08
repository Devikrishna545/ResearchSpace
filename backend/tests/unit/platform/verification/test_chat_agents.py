import json
import pytest

from app.core.exceptions import DraftParseError
from app.core.config import Settings
from app.modules.chat.agents.answer_agent import AnswerAgent
from app.modules.chat.schemas.chat import Claim, Draft, EvidenceSet, ScoredChunk
from app.platform.llm.model_router import ModelRouter
from app.platform.verification.peer_reviewer_agent import PeerReviewerAgent


class RecordingLLM:
    def __init__(self, response):
        self.response = response
        self.messages = []
        self.options = {}

    async def chat(self, messages, model, **kwargs):
        self.messages = messages
        self.options = kwargs
        return self.response


async def test_trailing_citations_stay_with_their_claim():
    llm = RecordingLLM(json.dumps({"claims": [
        {"text": "First fact. [paper-a-0]", "cited_chunk_ids": ["paper-a-0"]},
        {"text": "Second fact [paper-b-1].", "cited_chunk_ids": ["paper-b-1"]},
    ]}))
    evidence = EvidenceSet(chunks=[ScoredChunk(chunk_id=cid, text="evidence") for cid in ["paper-a-0", "paper-b-1"]])
    draft = await AnswerAgent(llm, ModelRouter(Settings())).generate("question", evidence)
    assert len(draft.claims) == 2
    assert draft.claims[0].cited_chunk_ids == ["paper-a-0"]
    assert draft.claims[1].cited_chunk_ids == ["paper-b-1"]
    assert draft.claims[0].text == "First fact [paper-a-0]."
    assert llm.options["schema"]["properties"]["claims"]["maxItems"] == 5
    assert llm.options["schema"]["$defs"]["_AnswerClaim"]["properties"]["cited_chunk_ids"]["items"]["enum"] == ["paper-a-0", "paper-b-1"]


@pytest.mark.parametrize("response", [
    "not json",
    json.dumps({"claims": [{"text": "Fact", "cited_chunk_ids": ["invented"]}]}),
    json.dumps({"claims": [{"text": "Fact", "cited_chunk_ids": []}]}),
    json.dumps({"claims": [{"text": "Fact", "cited_chunk_ids": ["e1"]}] * 6}),
])
async def test_invalid_generated_claims_fail_explicitly(response):
    with pytest.raises(DraftParseError):
        await AnswerAgent(RecordingLLM(response), ModelRouter(Settings())).generate(
            "question", EvidenceSet(chunks=[ScoredChunk(chunk_id="e1", text="evidence")]),
        )


async def test_reviewer_receives_exact_claim_contract_and_source_identity():
    llm = RecordingLLM(json.dumps({"verdict": "APPROVED", "overall_score": 1, "claims": []}))
    evidence = EvidenceSet(chunks=[ScoredChunk(
        chunk_id="paper-a-0", paper_id="paper-a", source="Tensor quantum programming",
        text="A tensor network method.", page=2, section="Methods",
    )])
    draft = Draft(text="A tensor method [paper-a-0].", claims=[
        Claim(claim_id="c7", text="A tensor method [paper-a-0].", cited_chunk_ids=["paper-a-0"]),
    ])
    await PeerReviewerAgent(llm, ModelRouter(Settings())).review("question", evidence, draft)
    prompt = llm.messages[-1]["content"]
    assert '"c7"' in prompt
    assert "Tensor quantum programming" in prompt
    assert "Methods" in prompt
    schema = llm.options["schema"]
    assert schema["$defs"]["ClaimFinding"]["properties"]["claim_id"]["enum"] == ["c7"]
    assert schema["properties"]["claims"]["minItems"] == 1
    assert schema["properties"]["claims"]["maxItems"] == 1
