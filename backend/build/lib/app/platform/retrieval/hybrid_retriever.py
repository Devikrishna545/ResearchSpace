from app.platform.retrieval.context_builder import ContextBuilder
from app.platform.retrieval.fusion import ReciprocalRankFusion
from app.platform.retrieval.mmr import MMR
from app.platform.retrieval.reranker import Reranker
from app.platform.retrieval.sparse_search import SparseSearch
class HybridRetriever:
    def __init__(self,dense=None,sparse=None,embedder=None):
        self.dense=dense; self.sparse=sparse or SparseSearch([]); self.embedder=embedder; self.fusion=ReciprocalRankFusion(); self.reranker=Reranker(); self.mmr=MMR(); self.context_builder=ContextBuilder()
    async def retrieve(self,space_id:str,question:str,scope:list[str]|None=None,extra_queries:list[str]|None=None):
        dense_lists=[]
        queries=list(dict.fromkeys([question]+[q for q in (extra_queries or []) if q]))
        if self.dense and self.embedder:
            vectors=await self.embedder(queries)
            for qvec in vectors:
                hits=await self.dense.search(space_id,qvec,50)
                dense_lists.append(hits)
        sparse_hits=await self.sparse.search(' '.join(queries),space_id,50)
        fused=self.fusion.fuse(*dense_lists,sparse_hits); reranked=await self.reranker.rerank(question,fused,top_k=12); diverse=self.mmr.diversify(reranked,top_k=8)
        return self.context_builder.pack(diverse,question)
