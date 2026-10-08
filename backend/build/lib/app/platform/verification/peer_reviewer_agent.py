from app.platform.llm.model_router import ModelTier
from app.platform.llm.prompts.loader import PromptLoader
from app.platform.verification.schemas import ClaimFinding,ClaimStatus,ReviewVerdict,VerdictType
from app.platform.verification.verdict_parser import VerdictParser
class PeerReviewerAgent:
    name='peer_reviewer_agent'
    def __init__(self,llm=None,router=None,prompts:PromptLoader|None=None): self.llm=llm; self.router=router; self.prompts=prompts or PromptLoader(); self.parser=VerdictParser()
    async def review(self,question,evidence,draft,iteration:int=1)->ReviewVerdict:
        if self.llm and self.router:
            system=self.prompts.render('peer_reviewer/system.jinja')
            user=self.prompts.render('peer_reviewer/user.jinja',question=question,evidence=evidence,draft=draft)
            model=self.router.model_for(ModelTier.LARGE if iteration>=3 else ModelTier.VERIFY)
            raw=await self.llm.chat([{'role':'system','content':system},{'role':'user','content':user}],model,temperature=0.0,json_format=True)
            return self.parser.parse(raw)
        ids={c.chunk_id for c in evidence.chunks}; findings=[]
        for claim in draft.claims:
            status=ClaimStatus.SUPPORTED if claim.cited_chunk_ids and all(cid in ids for cid in claim.cited_chunk_ids) else (ClaimStatus.MISCITED if claim.cited_chunk_ids else ClaimStatus.UNSUPPORTED)
            findings.append(ClaimFinding(claim_id=claim.claim_id,claim_text=claim.text,status=status,cited_chunk_ids=claim.cited_chunk_ids,issue='' if status==ClaimStatus.SUPPORTED else 'Claim is not fully grounded.'))
        bad=[f for f in findings if f.status in {ClaimStatus.UNSUPPORTED,ClaimStatus.CONTRADICTED,ClaimStatus.MISCITED}]
        return ReviewVerdict(verdict=VerdictType.APPROVED if not bad else VerdictType.REVISE,overall_score=1.0 if not bad else 0.5,claims=findings)
