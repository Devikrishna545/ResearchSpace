class Convergence:
    def __init__(self,min_improvement:float=0.05): self.min_improvement=min_improvement
    def has_stalled(self,history)->bool:
        if len(history)<3: return False
        s=[v.overall_score for v in history[-3:]]; return (s[1]-s[0])<self.min_improvement and (s[2]-s[1])<self.min_improvement
    def has_ungrounded_stall(self,history)->bool:
        if len(history)<2: return False
        from app.platform.verification.schemas import ClaimStatus
        last=history[-2:]
        return all(not any(f.status==ClaimStatus.SUPPORTED and f.cited_chunk_ids for f in v.claims) for v in last) and last[1].overall_score-last[0].overall_score<self.min_improvement
