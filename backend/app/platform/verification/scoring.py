from app.platform.verification.schemas import ClaimStatus
def groundedness_score(verdict):
    if not verdict.claims: return verdict.overall_score
    return min(verdict.overall_score, sum(1 for c in verdict.claims if c.status==ClaimStatus.SUPPORTED)/len(verdict.claims))
