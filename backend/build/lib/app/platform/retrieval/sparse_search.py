import math
from collections import Counter
from app.modules.chat.schemas.chat import ScoredChunk
from app.shared.text import tokenize
class SparseSearch:
    def __init__(self,chunks:list[ScoredChunk]|None=None): self.chunks=chunks or []
    async def search(self,query:str,space_id:str|None=None,k:int=50)->list[ScoredChunk]:
        q=tokenize(query); docs=[tokenize(c.text) for c in self.chunks]
        if not q or not docs: return []
        df=Counter(t for d in docs for t in set(d)); n=len(docs); hits=[]
        for c,terms in zip(self.chunks,docs,strict=False):
            tf=Counter(terms); score=sum(tf[t]*math.log((n+1)/(df[t]+1)) for t in q)
            if score>0: hits.append(c.model_copy(update={'score':score}))
        return sorted(hits,key=lambda c:c.score,reverse=True)[:k]
