from app.modules.chat.schemas.chat import ScoredChunk
class ReciprocalRankFusion:
    def __init__(self,k:int=60): self.k=k
    def fuse(self,*ranked_lists:list[ScoredChunk])->list[ScoredChunk]:
        scores={}; best={}
        for ranked in ranked_lists:
            seen=set()
            unique_rank=0
            for chunk in ranked:
                if chunk.chunk_id in seen: continue
                seen.add(chunk.chunk_id); unique_rank += 1
                scores[chunk.chunk_id]=scores.get(chunk.chunk_id,0.0)+1.0/(self.k+unique_rank); best.setdefault(chunk.chunk_id,chunk)
        return [best[cid].model_copy(update={'score':score}) for cid,score in sorted(scores.items(),key=lambda i:i[1],reverse=True)]
