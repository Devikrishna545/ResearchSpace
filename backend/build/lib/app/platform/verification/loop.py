import asyncio
import logging
import re
from time import perf_counter
from uuid import uuid4

from app.core.exceptions import LLMUnavailableError, VerdictParseError
from app.modules.chat.schemas.chat import AnsweredTurn, CitationDTO
from app.platform.verification.schemas import ClaimStatus, LoopAction, LoopTrace, ReviewVerdict, VerdictType
from app.platform.llm.model_router import ModelTier
from app.platform.verification.grounding import match_claims
from app.platform.verification.scoring import groundedness_score
from app.platform.verification.trail import VerificationTrail

logger = logging.getLogger(__name__)

class VerificationLoopDriver:
    """Plain async loop driver. TODO: slot into LangGraph/Celery later."""

    def __init__(self, retriever, answer_agent, reviewer_agent, controller, trail=None, embedder=None):
        self.retriever = retriever
        self.answer_agent = answer_agent
        self.reviewer_agent = reviewer_agent
        self.controller = controller
        self.trail = trail or VerificationTrail()
        self.embedder = embedder

    def _models_used(self, iteration):
        parts = []
        for name, agent, tier in (
            ('answer', self.answer_agent, ModelTier.MEDIUM),
            ('review', self.reviewer_agent, ModelTier.LARGE if iteration >= 3 else ModelTier.VERIFY),
        ):
            if getattr(agent, 'llm', None) and getattr(agent, 'router', None):
                parts.append(f'{name}={agent.router.model_for(tier)}')
        return '; '.join(parts) or None

    def _needs_joint_evidence(self, question, evidence):
        return bool(re.search(r'\b(?:both|shared|same|identical|similarit\w*|commonalit\w*)\b', question, re.I)
                    and len({c.paper_id for c in evidence.chunks if c.paper_id}) >= 2)

    async def run(self, space_id: str, question: str, turn_id: str | None = None, extra_queries: list[str] | None = None):
        turn_id = turn_id or str(uuid4())
        start = perf_counter()
        traces = []
        history = []
        best_draft = None
        best_verdict = None
        best_evidence = None
        best_matches = None
        best_model = None
        evidence = None
        extra = list(extra_queries or [])
        try:
            async with asyncio.timeout(self._remaining_seconds(start)):
                evidence = await self.retriever.retrieve(space_id, question, extra_queries=extra_queries)
        except (TimeoutError, LLMUnavailableError) as exc:
            verdict = self._synthetic_verdict(f'Initial retrieval failed or timed out: {exc}', 0.0)
            traces.append(LoopTrace(iteration=0, draft_text='', verdict=verdict, action_taken=LoopAction.ABSTAIN, latency_ms=int((perf_counter() - start) * 1000)))
            await self.trail.persist(turn_id, traces)
            return self._with_traces(self._abstain(turn_id, evidence, verdict, 0, 'Low confidence: the model was unavailable before an answer could be verified.'), traces)

        while True:
            try:
                async with asyncio.timeout(self._remaining_seconds(start)):
                    iteration = len(history) + 1
                    it = perf_counter()
                    draft = await self.answer_agent.generate(question, evidence, history)
                    try:
                        verdict = await self.reviewer_agent.review(question, evidence, draft, iteration=iteration)
                    except VerdictParseError:
                        verdict = ReviewVerdict(verdict=VerdictType.REVISE, overall_score=0.0, global_feedback='Reviewer output was unparseable. Rewrite the answer as short factual sentences, each citing evidence chunk ids in [brackets].')
                    joint = self._needs_joint_evidence(question, evidence)
                    verdict = self.controller.prepare_verdict(verdict, draft, evidence, require_joint_evidence=joint)
                    matches = None
                    if self.embedder:
                        try:
                            matches = await asyncio.wait_for(match_claims(draft.claims, evidence, self.embedder), timeout=min(5, self._remaining_seconds(start)))
                        except (TimeoutError, LLMUnavailableError, ValueError):
                            logger.warning('Citation embedding unavailable; using legacy excerpts without deterministic grounding', exc_info=True)
                        else:
                            verdict = self.controller.prepare_verdict(verdict, draft, evidence, matches, require_joint_evidence=joint)
                    history.append(verdict)
                    quality = lambda v: (sum(f.status == ClaimStatus.SUPPORTED and bool(f.cited_chunk_ids) for f in v.claims), v.overall_score)
                    if best_verdict is None or quality(verdict) > quality(best_verdict):
                        # Keep the evidence that produced this draft: citations must be
                        # validated against it, not against a later re-retrieved set.
                        best_draft, best_verdict, best_evidence, best_matches = draft, verdict, evidence, matches
                        best_model = self._models_used(iteration)
                    action = self.controller.decide(verdict, iteration, int((perf_counter() - start) * 1000), history, draft, evidence, require_joint_evidence=joint)
                    traces.append(LoopTrace(iteration=iteration, draft_text=draft.text, verdict=verdict, action_taken=action, latency_ms=int((perf_counter() - it) * 1000), model_used=self._models_used(iteration)))
                    if action == LoopAction.ACCEPT:
                        await self.trail.persist(turn_id, traces)
                        return self._with_traces(self._answered(turn_id, draft, verdict, evidence, len(history), True, matches=matches), traces)
                    if action == LoopAction.ABSTAIN or (action == LoopAction.FINALIZE_BEST_EFFORT and verdict.verdict == VerdictType.REJECT):
                        await self.trail.persist(turn_id, traces)
                        return self._with_traces(self._abstain(turn_id, best_evidence or evidence, best_verdict or verdict, len(history)), traces)
                    if action == LoopAction.FINALIZE_BEST_EFFORT:
                        await self.trail.persist(turn_id, traces)
                        if joint:
                            return self._with_traces(self._abstain(turn_id, evidence, verdict, len(history), 'Low confidence: the papers do not jointly substantiate the requested comparison.'), traces)
                        return self._with_traces(self._finalize_best_effort(turn_id, best_draft or draft, best_verdict or verdict, best_evidence if best_draft else evidence, len(history), best_matches), traces)
                    if action == LoopAction.RE_RETRIEVE:
                        extra.extend(verdict.missing_evidence_queries or [question])
                        evidence = await self.retriever.retrieve(space_id, question, extra_queries=extra)
            except (TimeoutError, LLMUnavailableError) as exc:
                verdict = self._synthetic_verdict(f'Model unavailable or wall-clock budget exhausted: {exc}', 0.0)
                traces.append(LoopTrace(iteration=len(history) + 1, draft_text=best_draft.text if best_draft else '', verdict=verdict, action_taken=LoopAction.FINALIZE_BEST_EFFORT if best_draft else LoopAction.ABSTAIN, latency_ms=int((perf_counter() - start) * 1000), model_used=best_model))
                await self.trail.persist(turn_id, traces)
                if best_draft:
                    if self._needs_joint_evidence(question, best_evidence or evidence):
                        return self._with_traces(self._abstain(turn_id, best_evidence or evidence, best_verdict or verdict, len(history), 'Low confidence: the papers do not jointly substantiate the requested comparison.'), traces)
                    result = self._finalize_best_effort(turn_id, best_draft, best_verdict or verdict, best_evidence or evidence, len(history), best_matches)
                    result.low_confidence_warning = 'Low confidence: the model was unavailable or timed out; returning the best verified draft so far.'
                    return self._with_traces(result, traces)
                return self._with_traces(self._abstain(turn_id, evidence, verdict, len(history), 'Low confidence: the model was unavailable before an answer could be verified.'), traces)

    def _remaining_seconds(self, start):
        remaining_ms = self.controller.policies.wall_clock_cap_ms - int((perf_counter() - start) * 1000)
        return max(0.001, remaining_ms / 1000)

    def _synthetic_verdict(self, message, score):
        return ReviewVerdict(verdict=VerdictType.REVISE, overall_score=score, global_feedback=message)

    def _with_traces(self, result, traces):
        result.verification_traces = list(traces)
        return result

    def _answered(self, turn_id, draft, verdict, evidence, iterations, verified, claims=None, answer=None, matches=None):
        claims = claims if claims is not None else draft.claims
        evidence_by_id = {c.chunk_id: c for c in (evidence.chunks if evidence else [])}
        citations = []
        for claim in claims:
            for cid in claim.cited_chunk_ids:
                chunk = evidence_by_id.get(cid)
                if chunk:
                    matched = matches.get((claim.claim_id, cid)) if matches is not None else None
                    citations.append(CitationDTO(marker=len(citations)+1, paper_id=chunk.paper_id, chunk_id=cid, page=chunk.page, section=chunk.section, quote=matched[0] if matched else chunk.text[:200], claim_text=claim.text, match_score=matched[1] if matched else None))
        return AnsweredTurn(turn_id=turn_id, answer=answer if answer is not None else draft.text, citations=citations, confidence=groundedness_score(verdict), iterations=iterations, verified=verified, low_confidence_warning=None if verified else 'Low confidence: verification did not approve this answer; unsupported claims may be flagged or omitted.', verification_url=f'/v1/turns/{turn_id}/verification')

    def _finalize_best_effort(self, turn_id, draft, verdict, evidence, iterations, matches=None):
        findings = {f.claim_id: f for f in verdict.claims}
        surviving = []
        texts = []
        for claim in draft.claims:
            finding = findings.get(claim.claim_id)
            if not finding:
                continue
            if finding.status == ClaimStatus.SUPPORTED and claim.cited_chunk_ids:
                surviving.append(claim)
                texts.append(claim.text)
            elif finding.status == ClaimStatus.PARTIAL and claim.cited_chunk_ids:
                surviving.append(claim)
                texts.append(claim.text + ' (partially supported)')
        if not surviving:
            return self._abstain(turn_id, evidence, verdict, iterations)
        return self._answered(turn_id, draft, verdict, evidence, iterations, False, claims=surviving, answer=' '.join(texts), matches=matches)

    def _abstain(self, turn_id, evidence, verdict, iterations, warning=None):
        titles = []
        for chunk in (evidence.chunks if evidence else []):
            title = (chunk.metadata or {}).get('title') or chunk.source or chunk.paper_id
            if title and title not in titles:
                titles.append(title)
        note = (' Evidence was found in ' + ', '.join(titles[:3]) + '.') if titles else ''
        return AnsweredTurn(turn_id=turn_id, answer='Not answerable from the attached papers.' + note + ' Try a narrower question about one paper or a specific finding.', citations=[], confidence=groundedness_score(verdict), iterations=iterations, verified=False, low_confidence_warning=warning or 'Low confidence: verification did not approve this answer; unsupported claims may be flagged or omitted.', verification_url=f'/v1/turns/{turn_id}/verification')
