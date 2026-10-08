from enum import StrEnum
from pydantic import BaseModel, Field
class ClaimStatus(StrEnum): SUPPORTED='SUPPORTED'; PARTIAL='PARTIAL'; UNSUPPORTED='UNSUPPORTED'; CONTRADICTED='CONTRADICTED'; MISCITED='MISCITED'
class VerdictType(StrEnum): APPROVED='APPROVED'; REVISE='REVISE'; EVIDENCE_GAP='EVIDENCE_GAP'; REJECT='REJECT'
class LoopAction(StrEnum): ACCEPT='ACCEPT'; REGENERATE='REGENERATE'; RE_RETRIEVE='RE_RETRIEVE'; ABSTAIN='ABSTAIN'; FINALIZE_BEST_EFFORT='FINALIZE_BEST_EFFORT'
class ClaimFinding(BaseModel):
    claim_id:str; claim_text:str=''; status:ClaimStatus; cited_chunk_ids:list[str]=Field(default_factory=list); evidence_quote:str=''; issue:str=''; suggested_correction:str=''
class ReviewVerdict(BaseModel):
    verdict:VerdictType; overall_score:float=Field(ge=0.0,le=1.0); claims:list[ClaimFinding]=Field(default_factory=list); missing_evidence_queries:list[str]=Field(default_factory=list); global_feedback:str=''; hallucination_flags:list[str]=Field(default_factory=list)
class LoopTrace(BaseModel): iteration:int; draft_text:str; verdict:ReviewVerdict; action_taken:LoopAction; latency_ms:int=0; model_used:str|None=None
