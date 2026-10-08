import math, httpx
from app.core.config import Settings
from app.platform.retrieval.vectorstore.interface import VectorStore
class InMemoryVectorStore(VectorStore):
    def __init__(self): self._data={}
    async def upsert(self,space_id,chunks,vectors):
        if len(chunks)!=len(vectors): raise ValueError('chunk/vector count mismatch')
        space=self._data.setdefault(space_id,{})
        for chunk, vector in zip(chunks,vectors,strict=True):
            space[chunk.chunk_id]=(chunk,vector)
    async def search(self,space_id,vector,k=10):
        def cos(a,b):
            if not a or not b or len(a)!=len(b): return None
            den=math.sqrt(sum(x*x for x in a))*math.sqrt(sum(x*x for x in b)); return sum(x*y for x,y in zip(a,b,strict=False))/den if den else 0.0
        hits=[]
        for c,v in self._data.get(space_id,{}).values():
            score=cos(vector,v)
            if score is not None: hits.append(c.model_copy(update={'score':score}))
        return sorted(hits,key=lambda c:c.score,reverse=True)[:k]
    async def health_check(self): return True
class QdrantVectorStore(InMemoryVectorStore):
    def __init__(self,settings:Settings): super().__init__(); self.settings=settings
    async def health_check(self):
        if not self.settings.qdrant_url: return False
        try:
            async with httpx.AsyncClient(timeout=1.0) as c:
                r=await c.get(self.settings.qdrant_url.rstrip('/')+'/healthz'); return r.status_code<500
        except Exception: return False
