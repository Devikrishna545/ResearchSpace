import asyncio
from time import perf_counter

from app.core.exceptions import DraftParseError, LLMUnavailableError
from app.platform.verification.refinement_controller import RefinementController
from app.modules.chat.schemas.chat import Draft,Claim,EvidenceSet,ScoredChunk
from app.platform.verification.schemas import ClaimFinding,ClaimStatus,LoopAction,ReviewVerdict,VerdictType
from app.platform.verification.loop import VerificationLoopDriver
from app.platform.verification.policies import LoopPolicies
class FakeRetriever:
    def __init__(self): self.calls=0
    async def retrieve(self,space_id,question,scope=None,extra_queries=None):
        self.calls+=1; chunks=[ScoredChunk(chunk_id='e1',text='evidence')]
        if extra_queries: chunks.append(ScoredChunk(chunk_id='e2',text='more evidence'))
        return EvidenceSet(chunks=chunks,query=question)
class FakeAnswer:
    def __init__(self,draft=None): self.draft=draft
    async def generate(self,question,evidence,feedback_history=None):
        if self.draft: return self.draft
        cid='e2' if any(c.chunk_id=='e2' for c in evidence.chunks) else 'e1'
        return Draft(text=f'answer [{cid}]',claims=[Claim(claim_id='c1',text='answer',cited_chunk_ids=[cid])])
class FakeReviewer:
    def __init__(self,verdicts): self.verdicts=verdicts; self.calls=0
    async def review(self,question,evidence,draft,iteration=1):
        v=self.verdicts[min(self.calls,len(self.verdicts)-1)]; self.calls+=1; return v
def v(score,status=ClaimStatus.SUPPORTED,kind=VerdictType.APPROVED): return ReviewVerdict(verdict=kind,overall_score=score,claims=[ClaimFinding(claim_id='c1',status=status)],missing_evidence_queries=['more'])
def driver(verdicts,max_iterations=3,answer=None): return VerificationLoopDriver(FakeRetriever(),answer or FakeAnswer(),FakeReviewer(verdicts),RefinementController(LoopPolicies(max_iterations=max_iterations)))
async def test_first_pass_approve():
    result=await driver([v(0.95)]).run('s','q')
    assert result.verified and result.iterations==1
async def test_revise_then_approve():
    result=await driver([v(0.6,ClaimStatus.PARTIAL,VerdictType.REVISE),v(0.95)]).run('s','q')
    assert result.verified and result.iterations==2
async def test_evidence_gap_reretrieve():
    d=driver([v(0.4,ClaimStatus.UNSUPPORTED,VerdictType.EVIDENCE_GAP),v(0.95)])
    result=await d.run('s','q')
    assert result.verified and result.iterations==2
    assert d.retriever.calls==2
async def test_budget_exhaustion_returns_best_flagged():
    result=await driver([v(0.4,ClaimStatus.PARTIAL,VerdictType.REVISE),v(0.5,ClaimStatus.PARTIAL,VerdictType.REVISE)],max_iterations=2).run('s','q')
    assert not result.verified
    assert result.iterations==2
    assert result.low_confidence_warning
async def test_finalize_best_effort_strips_unsupported_claims():
    draft=Draft(text='supported fact unsupported fact',claims=[Claim(claim_id='c1',text='supported fact',cited_chunk_ids=['e1']),Claim(claim_id='c2',text='unsupported fact',cited_chunk_ids=['e1'])])
    verdict=ReviewVerdict(verdict=VerdictType.REVISE,overall_score=0.5,claims=[ClaimFinding(claim_id='c1',status=ClaimStatus.SUPPORTED),ClaimFinding(claim_id='c2',status=ClaimStatus.UNSUPPORTED)])
    result=await driver([verdict],max_iterations=1,answer=FakeAnswer(draft)).run('s','q')
    assert not result.verified
    assert result.answer=='supported fact'
    assert 'unsupported fact' not in result.answer
    assert [c.chunk_id for c in result.citations]==['e1']
async def test_finalize_best_effort_all_claims_bad_abstains():
    draft=Draft(text='unsupported fact',claims=[Claim(claim_id='c1',text='unsupported fact',cited_chunk_ids=['e1'])])
    verdict=ReviewVerdict(verdict=VerdictType.REVISE,overall_score=0.5,claims=[ClaimFinding(claim_id='c1',status=ClaimStatus.UNSUPPORTED)])
    result=await driver([verdict],max_iterations=1,answer=FakeAnswer(draft)).run('s','q')
    assert result.answer.startswith('Not answerable from the attached papers.')
    assert result.citations==[]
async def test_reject_at_exhaustion_abstains_instead_of_returning_draft():
    draft=Draft(text='rejected draft',claims=[Claim(claim_id='c1',text='rejected draft',cited_chunk_ids=['e1'])])
    verdict=ReviewVerdict(verdict=VerdictType.REJECT,overall_score=0.2,claims=[ClaimFinding(claim_id='c1',status=ClaimStatus.CONTRADICTED)])
    result=await driver([verdict],max_iterations=1,answer=FakeAnswer(draft)).run('s','q')
    assert result.answer.startswith('Not answerable from the attached papers.')
    assert 'rejected draft' not in result.answer

class SlowSecondAnswer(FakeAnswer):
    def __init__(self):
        super().__init__()
        self.calls=0
    async def generate(self,question,evidence,feedback_history=None):
        self.calls+=1
        if self.calls>1:
            await asyncio.sleep(1)
        return await super().generate(question,evidence,feedback_history)

async def test_wall_clock_timeout_returns_best_effort_quickly():
    policies=LoopPolicies(max_iterations=3,wall_clock_cap_ms=50)
    drv=VerificationLoopDriver(FakeRetriever(),SlowSecondAnswer(),FakeReviewer([v(0.5,ClaimStatus.PARTIAL,VerdictType.REVISE)]),RefinementController(policies))
    start=perf_counter()
    result=await drv.run('s','q')
    assert perf_counter()-start<0.5
    assert not result.verified
    assert result.low_confidence_warning
    assert result.verification_traces[-1].action_taken==LoopAction.FINALIZE_BEST_EFFORT

class UnavailableAnswer:
    async def generate(self,question,evidence,feedback_history=None):
        raise LLMUnavailableError('down')

async def test_llm_unavailable_returns_warning_not_exception():
    result=await VerificationLoopDriver(FakeRetriever(),UnavailableAnswer(),FakeReviewer([v(1.0)]),RefinementController(LoopPolicies())).run('s','q')
    assert result.answer.startswith('Not answerable')
    assert 'unavailable' in result.low_confidence_warning

async def test_citations_resolve_to_evidence_metadata_and_text():
    evidence=EvidenceSet(chunks=[ScoredChunk(chunk_id='e1',paper_id='p1',text='Evidence quote text, not claim text.',section='Methods',page=7)])
    class Retriever:
        async def retrieve(self,*args,**kwargs): return evidence
    result=await VerificationLoopDriver(Retriever(),FakeAnswer(),FakeReviewer([v(0.95)]),RefinementController(LoopPolicies())).run('s','q')
    assert result.citations[0].paper_id=='p1'
    assert result.citations[0].section=='Methods'
    assert result.citations[0].page==7
    assert result.citations[0].quote.startswith('Evidence quote text')


class DisjointRetriever:
    """Second retrieval returns a completely different evidence set (no overlapping ids)."""
    def __init__(self): self.calls=0
    async def retrieve(self,space_id,question,scope=None,extra_queries=None):
        self.calls+=1
        if self.calls==1: return EvidenceSet(chunks=[ScoredChunk(chunk_id='e1',text='first evidence')],query=question)
        return EvidenceSet(chunks=[ScoredChunk(chunk_id='z9',text='different evidence')],query=question)
class FixedDraftAnswer:
    async def generate(self,question,evidence,feedback_history=None):
        return Draft(text='cited fact [e1]',claims=[Claim(claim_id='c1',text='cited fact',cited_chunk_ids=['e1'])])
async def test_best_draft_keeps_its_own_evidence_for_citations():
    # iter1 scores best against e1; iter2 re-retrieves disjoint evidence. The finalized
    # best draft must keep its e1 citation rather than losing it against the new set.
    verdicts=[ReviewVerdict(verdict=VerdictType.EVIDENCE_GAP,overall_score=0.8,claims=[ClaimFinding(claim_id='c1',status=ClaimStatus.PARTIAL)],missing_evidence_queries=['more']),
              ReviewVerdict(verdict=VerdictType.REVISE,overall_score=0.1,claims=[ClaimFinding(claim_id='c1',status=ClaimStatus.PARTIAL)])]
    drv=VerificationLoopDriver(DisjointRetriever(),FixedDraftAnswer(),FakeReviewer(verdicts),RefinementController(LoopPolicies(max_iterations=2)))
    result=await drv.run('s','q')
    assert not result.verified
    assert [c.chunk_id for c in result.citations]==['e1']
    assert result.citations[0].quote.startswith('first evidence')


async def test_windowed_quote_and_claim_text_are_distinct():
    text = ('Unrelated introduction about training parameters. ' * 12
            + 'GloVe outperforms word2vec on analogy, similarity, and named entity recognition.')
    class Retriever:
        async def retrieve(self, *args, **kwargs):
            return EvidenceSet(chunks=[ScoredChunk(chunk_id='e1', paper_id='p1', text=text)])
    class Answer:
        async def generate(self, *args):
            return Draft(text='GloVe outperforms word2vec [e1].', claims=[
                Claim(claim_id='c1', text='GloVe outperforms word2vec [e1].', cited_chunk_ids=['e1'])])
    async def embed(texts):
        return [[1.0, 0.0] if 'outperform' in t.lower() else [0.0, 1.0] for t in texts]
    result = await VerificationLoopDriver(
        Retriever(), Answer(), FakeReviewer([v(0.98)]), RefinementController(LoopPolicies()), embedder=embed
    ).run('s', 'How does GloVe compare?')
    assert result.verified
    assert 'outperforms word2vec' in result.citations[0].quote
    assert result.citations[0].claim_text == 'GloVe outperforms word2vec [e1].'
    assert result.citations[0].match_score == 1.0


async def test_unrelated_existing_chunk_is_miscited_and_cannot_be_accepted():
    class Retriever:
        async def retrieve(self, *args, **kwargs):
            return EvidenceSet(chunks=[ScoredChunk(chunk_id='e1', text='Unrelated passage about particle accelerators.')])
    class Answer:
        async def generate(self, *args):
            return Draft(text='GloVe outperforms word2vec [e1].', claims=[
                Claim(claim_id='c1', text='GloVe outperforms word2vec [e1].', cited_chunk_ids=['e1'])])
    async def embed(texts):
        return [[1.0, 0.0] if 'word2vec' in t.lower() else [0.0, 1.0] for t in texts]
    reviewer = FakeReviewer([v(0.98)])
    result = await VerificationLoopDriver(
        Retriever(), Answer(), reviewer, RefinementController(LoopPolicies()), embedder=embed
    ).run('s', 'How does GloVe compare?')
    assert not result.verified and result.citations == []
    assert result.iterations == 2 and reviewer.calls == 2
    assert 'narrower question' in result.answer
    assert all(trace.verdict.claims[0].status == ClaimStatus.MISCITED for trace in result.verification_traces)
    assert result.verification_traces[-1].action_taken == LoopAction.FINALIZE_BEST_EFFORT


async def test_cross_paper_partial_drafts_abstain_instead_of_repeating_unsupported_similarity():
    class Retriever:
        async def retrieve(self, *args, **kwargs):
            return EvidenceSet(chunks=[
                ScoredChunk(chunk_id='e1', paper_id='word2vec', text='Google News training corpus'),
                ScoredChunk(chunk_id='e2', paper_id='glove', text='Wikipedia and Gigaword training corpora'),
            ])
    class Answer:
        async def generate(self, *args):
            return Draft(text='Both use Google News [e1].', claims=[
                Claim(claim_id='c1', text='Both use Google News [e1].', cited_chunk_ids=['e1'])])
    async def embed(texts):
        return [[1.0] for _ in texts]
    result = await VerificationLoopDriver(
        Retriever(), Answer(), FakeReviewer([v(0.98)]),
        RefinementController(LoopPolicies()), embedder=embed,
    ).run('s', 'Which identical training dataset do both papers use?')
    assert not result.verified and result.iterations == 2
    assert result.citations == []
    assert result.answer.startswith('Not answerable')
    assert 'do not jointly substantiate' in result.low_confidence_warning


async def test_embedding_unavailable_falls_back_to_original_quote():
    async def unavailable(_):
        raise LLMUnavailableError('embed server unavailable')
    result = await VerificationLoopDriver(
        FakeRetriever(), FakeAnswer(), FakeReviewer([v(0.95)]),
        RefinementController(LoopPolicies()), embedder=unavailable,
    ).run('s', 'q')
    assert result.verified
    assert result.citations[0].quote == 'evidence'
    assert result.citations[0].match_score is None


async def test_invalid_answer_shape_is_a_visible_failure_not_a_verified_answer():
    class InvalidAnswer:
        async def generate(self, *args):
            raise DraftParseError("Answer cited a chunk outside the retrieved evidence.")
    reviewer = FakeReviewer([v(0.99)])
    result = await VerificationLoopDriver(
        FakeRetriever(), InvalidAnswer(), reviewer, RefinementController(LoopPolicies(max_iterations=1)),
    ).run("s", "q")
    assert not result.verified and not result.citations
    assert reviewer.calls == 0
    assert "outside the retrieved evidence" in result.verification_traces[0].verdict.global_feedback


async def test_best_effort_keeps_reviewed_claim_without_approving_missing_claim():
    draft = Draft(text="Known [e1]. Unknown [e1].", claims=[
        Claim(claim_id="c1", text="Known [e1].", cited_chunk_ids=["e1"]),
        Claim(claim_id="c2", text="Unknown [e1].", cited_chunk_ids=["e1"]),
    ])
    result = await driver([v(0.99)], max_iterations=1, answer=FakeAnswer(draft)).run("s", "q")
    assert not result.verified
    assert result.answer == "Known [e1]."
    assert len(result.citations) == 1
