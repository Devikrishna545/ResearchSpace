from app.modules.chat.schemas.chat import Claim,Draft,EvidenceSet,ScoredChunk
from app.platform.verification.schemas import ClaimFinding,ClaimStatus,ReviewVerdict,VerdictType,LoopAction
from app.platform.verification.convergence import Convergence
from app.platform.verification.policies import LoopPolicies

def verdict(score,status=ClaimStatus.SUPPORTED,kind=VerdictType.APPROVED): return ReviewVerdict(verdict=kind,overall_score=score,claims=[ClaimFinding(claim_id='c1',status=status)])
def test_acceptance_requires_threshold_and_no_bad_claims():
    p=LoopPolicies(3,20000,0.9)
    assert p.decide(verdict(0.95),1,1,[verdict(0.95)],Convergence())==LoopAction.ACCEPT
    assert p.decide(verdict(0.95,ClaimStatus.UNSUPPORTED),1,1,[verdict(0.95,ClaimStatus.UNSUPPORTED)],Convergence())==LoopAction.RE_RETRIEVE
def test_acceptance_requires_reviewer_claim_coverage():
    p=LoopPolicies(3,20000,0.9)
    draft=Draft(text='a b',claims=[Claim(claim_id='c1',text='a',cited_chunk_ids=['e1']),Claim(claim_id='c2',text='b',cited_chunk_ids=['e1'])])
    evidence=EvidenceSet(chunks=[ScoredChunk(chunk_id='e1',text='evidence')])
    empty=ReviewVerdict(verdict=VerdictType.APPROVED,overall_score=0.95,claims=[])
    omitted=ReviewVerdict(verdict=VerdictType.APPROVED,overall_score=0.95,claims=[ClaimFinding(claim_id='c1',status=ClaimStatus.SUPPORTED)])
    wrong_ids=ReviewVerdict(verdict=VerdictType.APPROVED,overall_score=0.95,claims=[
        ClaimFinding(claim_id='different-1',status=ClaimStatus.SUPPORTED),
        ClaimFinding(claim_id='different-2',status=ClaimStatus.SUPPORTED),
    ])
    assert p.decide(empty,1,1,[],Convergence(),draft,evidence)==LoopAction.REGENERATE
    assert p.decide(omitted,1,1,[],Convergence(),draft,evidence)==LoopAction.REGENERATE
    assert [f.status for f in p.prepare_verdict(omitted,draft,evidence).claims]==[ClaimStatus.SUPPORTED,ClaimStatus.UNSUPPORTED]
    assert all(f.status==ClaimStatus.UNSUPPORTED for f in p.prepare_verdict(wrong_ids,draft,evidence).claims)
def test_unknown_cited_chunk_is_deterministically_miscited():
    p=LoopPolicies(3,20000,0.9)
    draft=Draft(text='a',claims=[Claim(claim_id='c1',text='a',cited_chunk_ids=['missing'])])
    evidence=EvidenceSet(chunks=[ScoredChunk(chunk_id='e1',text='evidence')])
    approved=ReviewVerdict(verdict=VerdictType.APPROVED,overall_score=0.95,claims=[ClaimFinding(claim_id='c1',status=ClaimStatus.SUPPORTED)])
    prepared=p.prepare_verdict(approved,draft,evidence)
    assert prepared.claims[0].status==ClaimStatus.MISCITED
    assert p.decide(approved,1,1,[],Convergence(),draft,evidence)==LoopAction.REGENERATE
def test_routing_rules_and_budget():
    p=LoopPolicies(3,20000,0.9)
    assert p.decide(verdict(0.6,ClaimStatus.PARTIAL,VerdictType.REVISE),1,1,[],Convergence())==LoopAction.REGENERATE
    assert p.decide(verdict(0.6,ClaimStatus.UNSUPPORTED,VerdictType.EVIDENCE_GAP),1,1,[],Convergence())==LoopAction.RE_RETRIEVE
    assert p.decide(verdict(0.6,ClaimStatus.CONTRADICTED,VerdictType.REVISE),3,1,[],Convergence())==LoopAction.FINALIZE_BEST_EFFORT
def test_oscillation_stops():
    h=[verdict(0.50,ClaimStatus.PARTIAL,VerdictType.REVISE),verdict(0.52,ClaimStatus.PARTIAL,VerdictType.REVISE),verdict(0.53,ClaimStatus.PARTIAL,VerdictType.REVISE)]
    assert Convergence().has_stalled(h)
    assert LoopPolicies(max_iterations=5).decide(h[-1],3,1,h,Convergence())==LoopAction.FINALIZE_BEST_EFFORT

def test_missing_citation_is_not_approved():
    p=LoopPolicies()
    draft=Draft(text='unsupported assertion',claims=[Claim(claim_id='c1',text='unsupported assertion')])
    approved=verdict(0.99)
    prepared=p.prepare_verdict(approved,draft,EvidenceSet(chunks=[ScoredChunk(chunk_id='e1',text='evidence')]))
    assert prepared.claims[0].status==ClaimStatus.UNSUPPORTED

def test_empty_claim_list_is_not_approved_by_high_review_score():
    prepared=LoopPolicies().prepare_verdict(verdict(0.99),Draft(text='Generic answer with no claims.'),EvidenceSet())
    assert prepared.verdict==VerdictType.REVISE
    assert prepared.claims==[]

def test_grounding_threshold_is_applied_to_every_cited_chunk():
    p=LoopPolicies()
    draft=Draft(text='claim',claims=[Claim(claim_id='c1',text='claim',cited_chunk_ids=['e1','e2'])])
    evidence=EvidenceSet(chunks=[ScoredChunk(chunk_id='e1',text='match'),ScoredChunk(chunk_id='e2',text='unrelated')])
    prepared=p.prepare_verdict(verdict(0.99),draft,evidence,{('c1','e1'):('match',0.8),('c1','e2'):('unrelated',0.4)})
    assert prepared.claims[0].status==ClaimStatus.MISCITED
    assert prepared.claims[0].issue

def test_shared_finding_cannot_be_supported_by_one_paper():
    p=LoopPolicies()
    evidence=EvidenceSet(chunks=[
        ScoredChunk(chunk_id='e1',paper_id='word2vec',text='Google News dataset'),
        ScoredChunk(chunk_id='e2',paper_id='glove',text='Wikipedia dataset'),
    ])
    draft=Draft(text='Both papers use Google News [e1]',claims=[
        Claim(claim_id='c1',text='Both papers use Google News',cited_chunk_ids=['e1'])])
    prepared=p.prepare_verdict(verdict(0.98),draft,evidence,{('c1','e1'):('Google News dataset',0.8)},require_joint_evidence=True)
    assert prepared.claims[0].status==ClaimStatus.MISCITED
    assert 'both papers' in prepared.claims[0].issue
    assert p.decide(prepared,1,1,[],Convergence(),draft,evidence,require_joint_evidence=True)==LoopAction.REGENERATE

def test_empty_cited_passage_cannot_support_claim_without_embeddings():
    p=LoopPolicies()
    draft=Draft(text='claim [e1]',claims=[Claim(claim_id='c1',text='claim [e1]',cited_chunk_ids=['e1'])])
    prepared=p.prepare_verdict(verdict(0.99),draft,EvidenceSet(chunks=[ScoredChunk(chunk_id='e1',text='  ')]))
    assert prepared.claims[0].status==ClaimStatus.MISCITED


def test_partial_claim_is_not_verified_even_with_high_score():
    assert LoopPolicies().decide(verdict(0.99, ClaimStatus.PARTIAL), 1, 1, []) == LoopAction.REGENERATE


def test_bibliography_numbers_and_partial_ids_are_not_repaired_into_evidence():
    evidence = EvidenceSet(chunks=[ScoredChunk(chunk_id="paper-1", text="Evidence")])
    for cid in ["1", "paper", "aper-1"]:
        draft = Draft(text=f"Claim [{cid}]", claims=[Claim(claim_id="c1", text="Claim", cited_chunk_ids=[cid])])
        prepared = LoopPolicies().prepare_verdict(verdict(0.99), draft, evidence)
        assert prepared.claims[0].status == ClaimStatus.MISCITED


def test_duplicate_reviewer_ids_cannot_approve_a_claim():
    draft = Draft(text="Fact [e1]", claims=[Claim(claim_id="c1", text="Fact", cited_chunk_ids=["e1"])])
    review = verdict(0.99)
    review.claims.append(review.claims[0].model_copy())
    prepared = LoopPolicies().prepare_verdict(review, draft, EvidenceSet(chunks=[ScoredChunk(chunk_id="e1", text="Evidence")]))
    assert prepared.claims[0].status == ClaimStatus.UNSUPPORTED
