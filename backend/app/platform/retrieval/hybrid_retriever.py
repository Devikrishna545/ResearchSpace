import re

from app.shared.text import normalize_title
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
        # A direct definition/summary of a full paper title should not drift into
        # similarly named methods from other papers. Comparisons stay multi-paper.
        title_query=re.sub(r'^(?:what is|explain|describe|summarize|summary of) (?:the paper )?', '', normalize_title(question))
        chunks=self.sparse.chunks if isinstance(self.sparse,SparseSearch) else []
        named=[c for c in chunks if c.source and normalize_title(c.source)==title_query]
        paper_ids=set(scope) if scope is not None else {c.paper_id for c in named if c.paper_id}
        scoped=scope is not None or bool(paper_ids)
        queries=list(dict.fromkeys([question]+[q for q in (extra_queries or []) if q]))
        if self.dense and self.embedder:
            vectors=await self.embedder(queries)
            for qvec in vectors:
                hits=await self.dense.search(space_id,qvec,50)
                if scoped: hits=[c for c in hits if c.paper_id in paper_ids]
                dense_lists.append(hits)
        sparse_hits=await self.sparse.search(' '.join(queries),space_id,50)
        if scoped:
            sparse_hits=[c for c in sparse_hits if c.paper_id in paper_ids]
            dense_lists.append([c for c in chunks if c.paper_id in paper_ids])
        fused=self.fusion.fuse(*dense_lists,sparse_hits); reranked=await self.reranker.rerank(question,fused,top_k=12); diverse=self.mmr.diversify(reranked,top_k=8)
        return self.context_builder.pack(diverse,question)
