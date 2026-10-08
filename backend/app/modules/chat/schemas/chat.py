from pydantic import BaseModel, Field
from uuid import uuid4


class ScoredChunk(BaseModel):
    chunk_id: str
    paper_id: str | None = None
    text: str
    score: float = 0.0
    section: str | None = None
    page: int | None = None
    source: str | None = None
    metadata: dict = Field(default_factory=dict)


class EvidenceSet(BaseModel):
    chunks: list[ScoredChunk] = Field(default_factory=list)
    query: str | None = None


class ConversationTurnDTO(BaseModel):
    role: str
    content: str
    created_at: str | None = None


class ReferencedSessionDTO(BaseModel):
    """Another chat session the user @-mentioned in the current question."""
    session_id: str
    title: str
    summary: str | None = None
    recent_turns: list[ConversationTurnDTO] = Field(default_factory=list)


class ConversationContext(BaseModel):
    recent_turns: list[ConversationTurnDTO] = Field(default_factory=list)
    rolling_summary: str | None = None
    recalled_turns: list[ConversationTurnDTO] = Field(default_factory=list)
    findings: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    session_summary: str | None = None
    referenced_sessions: list[ReferencedSessionDTO] = Field(default_factory=list)

    def to_prompt(self) -> str:
        parts = []
        if self.rolling_summary:
            parts.append(f"Summary: {self.rolling_summary}")
        if self.session_summary:
            parts.append(f"Earlier in this conversation: {self.session_summary}")
        if self.findings:
            parts.append("Findings: " + "; ".join(self.findings[:8]))
        if self.open_questions:
            parts.append("Open questions: " + "; ".join(self.open_questions[:8]))
        if self.recent_turns:
            recent = " ".join(f"{turn.role}: {turn.content}" for turn in self.recent_turns[-6:])
            parts.append("Recent turns: " + recent)
        if self.recalled_turns:
            recalled = " ".join(f"{turn.role}: {turn.content}" for turn in self.recalled_turns[:4])
            parts.append("Relevant older turns: " + recalled)
        for ref in self.referenced_sessions:
            body = ref.summary or " ".join(f"{turn.role}: {turn.content}" for turn in ref.recent_turns)
            parts.append(f'Referenced conversation "{ref.title}": {body}')
        return "\n".join(parts)

    def __str__(self) -> str:
        return self.to_prompt()


class Claim(BaseModel):
    claim_id: str
    text: str
    cited_chunk_ids: list[str] = Field(default_factory=list)


class Draft(BaseModel):
    text: str
    claims: list[Claim] = Field(default_factory=list)
    citations: list[dict] = Field(default_factory=list)


class CitationDTO(BaseModel):
    marker: int
    paper_id: str | None = None
    chunk_id: str | None = None
    page: int | None = None
    section: str | None = None
    quote: str | None = None
    claim_text: str | None = None
    match_score: float | None = None


class TurnState(BaseModel):
    space_id: str
    turn_id: str = Field(default_factory=lambda: str(uuid4()))
    user_query: str
    evidence: EvidenceSet = Field(default_factory=EvidenceSet)
    draft: Draft | None = None
    review_history: list['ReviewVerdict'] = Field(default_factory=list)
    iteration: int = 0
    confidence: float = 0.0
    action_log: list[str] = Field(default_factory=list)


class AnsweredTurn(BaseModel):
    turn_id: str = Field(default_factory=lambda: str(uuid4()))
    answer: str
    citations: list[CitationDTO] = Field(default_factory=list)
    confidence: float = 0.0
    iterations: int = 0
    verified: bool = False
    low_confidence_warning: str | None = None
    verification_url: str | None = None
    session_id: str | None = None
    verification_traces: list['LoopTrace'] = Field(default_factory=list, exclude=True)


from app.platform.verification.schemas import ReviewVerdict
from app.platform.verification.schemas import LoopTrace
TurnState.model_rebuild()
AnsweredTurn.model_rebuild()
