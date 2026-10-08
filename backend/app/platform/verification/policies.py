from app.platform.verification.schemas import ClaimFinding,ClaimStatus,LoopAction,VerdictType
from app.platform.verification.grounding import MIN_GROUNDING_SIMILARITY
BAD_FOR_ACCEPTANCE={ClaimStatus.PARTIAL,ClaimStatus.UNSUPPORTED,ClaimStatus.CONTRADICTED,ClaimStatus.MISCITED}
class LoopPolicies:
    def __init__(self,max_iterations:int=3,wall_clock_cap_ms:int=20000,acceptance_threshold:float=0.90): self.max_iterations=max_iterations; self.wall_clock_cap_ms=wall_clock_cap_ms; self.acceptance_threshold=acceptance_threshold
    def prepare_verdict(self,verdict,draft=None,evidence=None,matches=None,require_joint_evidence=False):
        if draft is None: return verdict
        draft_claims=draft.claims or []
        if not draft_claims:
            feedback=(verdict.global_feedback+' ' if verdict.global_feedback else '')+'Draft has no verifiable claims.'
            return verdict.model_copy(update={'verdict':VerdictType.REVISE,'claims':[],'global_feedback':feedback})
        findings=list(verdict.claims or [])
        by_id={f.claim_id:f for f in findings if f.claim_id and sum(other.claim_id==f.claim_id for other in findings)==1}
        covered_by_id=all(c.claim_id in by_id for c in draft_claims)
        if covered_by_id:
            aligned=[by_id[c.claim_id] for c in draft_claims]
        else:
            feedback=(verdict.global_feedback+' ' if verdict.global_feedback else '')+'Reviewer must address every claim in the draft before it can be accepted.'
            aligned=[by_id.get(claim.claim_id) or ClaimFinding(claim_id=claim.claim_id,claim_text=claim.text,status=ClaimStatus.UNSUPPORTED,issue='Reviewer did not reliably address this claim.') for claim in draft_claims]
            verdict=verdict.model_copy(update={'verdict':VerdictType.REVISE,'global_feedback':feedback})
        evidence_ids={c.chunk_id for c in (evidence.chunks if evidence else [])}
        normalized=[]
        for finding,claim in zip(aligned,draft_claims):
            update={'claim_id':claim.claim_id,'claim_text':claim.text}
            if evidence is not None:
                resolved=[]; missing=[]
                for cid in claim.cited_chunk_ids:
                    rid=cid if cid in evidence_ids else None
                    if rid: resolved.append(rid)
                    else: missing.append(cid)
                if not claim.cited_chunk_ids:
                    update.update({'status':ClaimStatus.UNSUPPORTED,'issue':'Claim has no cited evidence.'})
                elif missing:
                    update.update({'status':ClaimStatus.MISCITED,'cited_chunk_ids':claim.cited_chunk_ids,'issue':'Claim cites chunks not present in the current evidence: '+', '.join(missing)})
                elif any(not c.text.strip() for c in evidence.chunks if c.chunk_id in resolved):
                    update.update({'status':ClaimStatus.MISCITED,'issue':'Cited passage contains no text.'})
                else:
                    claim.cited_chunk_ids=resolved
                    update['cited_chunk_ids']=resolved
                    if matches is not None and resolved and any(
                        matches.get((claim.claim_id, cid), ("", -1.0))[1] < MIN_GROUNDING_SIMILARITY
                        for cid in resolved
                    ):
                        update.update({'status':ClaimStatus.MISCITED,'issue':f'Cited passage does not substantiate the claim (minimum cosine {MIN_GROUNDING_SIMILARITY:.2f}).'})
                    elif require_joint_evidence and len({
                        c.paper_id for c in evidence.chunks if c.chunk_id in resolved and c.paper_id
                    }) < 2:
                        update.update({'status':ClaimStatus.MISCITED,'issue':'A shared finding needs cited evidence from both papers.'})
            normalized.append(finding.model_copy(update=update))
        return verdict.model_copy(update={'claims':normalized})
    def is_acceptable(self,verdict,draft=None,evidence=None)->bool:
        verdict=self.prepare_verdict(verdict,draft,evidence)
        return verdict.overall_score>=self.acceptance_threshold and verdict.verdict==VerdictType.APPROVED and not any(c.status in BAD_FOR_ACCEPTANCE for c in verdict.claims)
    def decide(self,verdict,iteration:int,elapsed_ms:int,history,convergence=None,draft=None,evidence=None,require_joint_evidence=False):
        verdict=self.prepare_verdict(verdict,draft,evidence,require_joint_evidence=require_joint_evidence)
        if self.is_acceptable(verdict): return LoopAction.ACCEPT
        if iteration>=self.max_iterations or elapsed_ms>=self.wall_clock_cap_ms or (convergence and (convergence.has_stalled(history) or convergence.has_ungrounded_stall(history))): return LoopAction.FINALIZE_BEST_EFFORT
        statuses={c.status for c in verdict.claims}
        if verdict.verdict==VerdictType.REVISE and any(c.issue=='Reviewer did not reliably address this claim.' for c in verdict.claims): return LoopAction.REGENERATE
        if verdict.verdict==VerdictType.EVIDENCE_GAP or ClaimStatus.UNSUPPORTED in statuses: return LoopAction.RE_RETRIEVE
        if verdict.verdict==VerdictType.REJECT: return LoopAction.ABSTAIN
        if statuses & {ClaimStatus.PARTIAL,ClaimStatus.MISCITED,ClaimStatus.CONTRADICTED} or verdict.verdict==VerdictType.REVISE: return LoopAction.REGENERATE
        return LoopAction.FINALIZE_BEST_EFFORT
