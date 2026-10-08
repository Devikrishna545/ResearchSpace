from collections import OrderedDict
from uuid import uuid4
from sqlalchemy import delete, select
from app.db.session import SessionLocal
from app.modules.chat.orm.verification_iteration import VerificationIteration
from app.platform.verification.schemas import ClaimFinding, ClaimStatus, LoopAction, LoopTrace, ReviewVerdict, VerdictType
class VerificationTrail:
    def __init__(self,session=None,max_memory:int=200): self.session=session; self.memory=OrderedDict(); self.max_memory=max_memory
    def _remember(self,turn_id:str,traces:list):
        self.memory[turn_id]=traces; self.memory.move_to_end(turn_id)
        while len(self.memory)>self.max_memory: self.memory.popitem(last=False)
    async def persist(self,turn_id:str,traces:list):
        self._remember(turn_id,traces)
        if not self.session: return
        await self.persist_to_session(turn_id,traces,self.session)
        await self.session.commit()
    async def persist_to_session(self,turn_id:str,traces:list,session):
        await session.execute(delete(VerificationIteration).where(VerificationIteration.turn_id==turn_id))
        for t in traces:
            session.add(VerificationIteration(id=str(uuid4()),turn_id=turn_id,iteration=t.iteration,draft_text=t.draft_text,verdict=t.verdict.verdict.value,overall_score=t.verdict.overall_score,claim_findings=[c.model_dump(mode='json') for c in t.verdict.claims],missing_evidence_queries=t.verdict.missing_evidence_queries,action_taken=t.action_taken.value,latency_ms=t.latency_ms,model_used=t.model_used,verdict_json=t.verdict.model_dump(mode='json')))
    async def get(self,turn_id):
        if self.session:
            rows=(await self.session.execute(select(VerificationIteration).where(VerificationIteration.turn_id==turn_id).order_by(VerificationIteration.iteration))).scalars().all()
            if rows: return [_row_to_trace(row) for row in rows]
        else:
            async with SessionLocal() as session:
                rows=(await session.execute(select(VerificationIteration).where(VerificationIteration.turn_id==turn_id).order_by(VerificationIteration.iteration))).scalars().all()
            if rows: return [_row_to_trace(row) for row in rows]
        return self.memory.get(turn_id,[])
    async def persist_to_db(self,turn_id:str):
        traces=self.memory.get(turn_id,[])
        if not traces: return
        async with SessionLocal() as session:
            await VerificationTrail(session=session).persist(turn_id,traces)

def _row_to_trace(row):
    verdict=ReviewVerdict.model_validate(row.verdict_json) if row.verdict_json else ReviewVerdict(verdict=VerdictType(row.verdict),overall_score=row.overall_score,claims=[ClaimFinding(**c) for c in row.claim_findings],missing_evidence_queries=row.missing_evidence_queries)
    return LoopTrace(iteration=row.iteration,draft_text=row.draft_text,verdict=verdict,action_taken=LoopAction(row.action_taken),latency_ms=row.latency_ms,model_used=row.model_used)
