"""Per-finding claim verification against original source spans, followed by display policy.

The narrow verifier sees only the finding's statement, its cited facts and their
primary excerpts. Its output is a warning signal combined with deterministic
policy checks; it is never treated as independent proof, and cosine similarity is
never used as an entailment gate.
"""

from app.modules.compare.grounded import normalizer as norm
from app.modules.compare.grounded.deterministic import PaperEvidence
from app.modules.compare.grounded.llm import GroundedLLM
from app.modules.compare.grounded.validation import context_window
from app.platform.llm.prompts.loader import PromptLoader
from app.modules.compare.schemas.grounded import (
    CANDIDATE_GAP, COMMONALITY, DIRECT_CONTRADICTION, EVIDENCE_BACKED_INTERPRETATION, INSUFFICIENT_EVIDENCE,
    PARTIALLY_SUPPORTED, SHOWN_STATUSES, UNSUPPORTED, Finding,
)

VERIFY_PROMPT_VERSION = "grounded-verify-v1"
VERDICTS = ("supported", "partially_supported", "unsupported", "insufficient_evidence")
SCHEMA = {
    "type": "object",
    "properties": {"verdict": {"type": "string", "enum": list(VERDICTS)}, "reason": {"type": "string"},
                   "unsupported_parts": {"type": "string"}},
    "required": ["verdict", "reason"],
}


def apply_display_policy(finding: Finding, final_authority: bool = True) -> Finding:
    if finding.display_status == "coverage":
        return finding
    if finding.evidence_status not in SHOWN_STATUSES:
        finding.display_status = "withheld"
    elif finding.evidence_status == PARTIALLY_SUPPORTED:
        finding.display_status = "shown_with_caveat"
    elif not final_authority:
        # The weak tier is never a final evidence authority, including for its extracted facts.
        finding.display_status = "shown_with_caveat"
        finding.reason = ((finding.reason or "") + " Generated on the weak-laptop tier; treat as a candidate only.").strip()
    else:
        finding.display_status = "shown"
    return finding


class FindingVerifier:
    def __init__(self, llm: GroundedLLM, papers: list[PaperEvidence], prompts: PromptLoader | None = None):
        self.llm = llm
        self.prompts = prompts or PromptLoader()
        self.papers = {p.paper_id: p for p in papers}
        self.facts = {f.id: (p, f) for p in papers for f in p.validated}

    def policy_check(self, finding: Finding) -> str | None:
        """Deterministic checks that must pass before any model is asked."""
        cited = [self.facts[i] for i in finding.fact_ids if i in self.facts]
        if len(cited) != len(finding.fact_ids):
            return "cites facts that are not validated for these papers"
        if not cited:
            return "no validated facts cited"
        supporting = {p.paper_id for p, _ in cited}
        named = set(finding.paper_ids)
        if not named <= supporting:
            return "a named paper has no cited evidence"
        if finding.kind in {COMMONALITY, DIRECT_CONTRADICTION} and len(named) < 2:
            return "a shared claim needs evidence from every paper it names"
        # Papers the statement itself claims to cover ("P3", "both", "all", "neither").
        required = set((finding.computed or {}).get("required_papers") or named)
        if not required <= supporting:
            return ("a candidate gap needs evidence from each relevant paper" if finding.kind == CANDIDATE_GAP
                    else "the statement covers a paper it cites no evidence from")
        return None

    async def verify(self, finding: Finding) -> Finding:
        problem = self.policy_check(finding)
        if problem:
            finding.evidence_status = INSUFFICIENT_EVIDENCE
            finding.verification_status = "policy_rejected"
            finding.reason = problem
            return finding
        evidence = []
        for fact_id in finding.fact_ids:
            paper, fact = self.facts[fact_id]
            source = paper.artifacts_by_id.get(fact.source_ids[0]) if fact.source_ids else None
            evidence.append({"label": paper.label, "title": paper.title, "fact_id": fact.id, "type": fact.fact_type,
                             "value": fact.value, "quote": fact.quote, "page": fact.page,
                             "excerpt": context_window(source.text, fact.quote, 400) if source else ""})
        result, _ = await self.llm.call(
            purpose=f"verify:{finding.kind}", prompt_version=VERIFY_PROMPT_VERSION,
            system=self.prompts.render("grounded/verify_system.jinja"),
            user=self.prompts.render("grounded/verify_user.jinja", statement=finding.statement, kind=finding.kind, evidence=evidence),
            single_object=True, schema=SCHEMA,
        )
        if not result.items:
            finding.evidence_status = INSUFFICIENT_EVIDENCE
            finding.verification_status = f"verifier_unavailable:{result.status}"
            finding.reason = "The verifier did not return a usable verdict, so this finding is withheld."
            return finding
        item = result.items[0]
        verdict = norm.verdict_word(norm.get_key(item, "verdict", "answer", "status"), VERDICTS, "insufficient_evidence")
        reason = str(norm.get_key(item, "reason", "explanation") or "").strip()
        unsupported = str(norm.get_key(item, "unsupported_parts") or "").strip()
        finding.verification_status = f"verifier:{verdict}"
        if verdict == "supported":
            finding.evidence_status = EVIDENCE_BACKED_INTERPRETATION
        elif verdict == "partially_supported":
            finding.evidence_status = PARTIALLY_SUPPORTED
            finding.reason = " ".join(x for x in (finding.reason, "Only partly supported: " + (unsupported or reason)) if x)
        elif verdict == "unsupported":
            finding.evidence_status = UNSUPPORTED
            finding.reason = reason or "The cited evidence does not support the statement."
        else:
            finding.evidence_status = INSUFFICIENT_EVIDENCE
            finding.reason = reason or "The cited evidence is not enough to support the statement."
        return finding
