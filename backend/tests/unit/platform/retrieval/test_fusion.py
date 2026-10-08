from app.platform.retrieval.fusion import ReciprocalRankFusion
from app.modules.chat.schemas.chat import ScoredChunk

def c(id): return ScoredChunk(chunk_id=id,text=id)
def test_rrf_math_and_order():
    fused=ReciprocalRankFusion(k=60).fuse([c('a'),c('b')],[c('b'),c('a')])
    assert fused[0].score==fused[1].score
    single=ReciprocalRankFusion(k=60).fuse([c('a'),c('b')],[c('b')])
    assert single[0].chunk_id=='b'
    assert round(single[0].score,6)==round(1/62+1/61,6)


def test_rrf_ignores_duplicates_within_one_ranked_list():
    fused = ReciprocalRankFusion(k=60).fuse([c('a'), c('a'), c('b')])
    scores = {chunk.chunk_id: chunk.score for chunk in fused}
    assert round(scores['a'], 6) == round(1/61, 6)
    assert round(scores['b'], 6) == round(1/62, 6)

async def test_hybrid_retriever_dense_searches_extra_queries():
    from app.platform.retrieval.hybrid_retriever import HybridRetriever

    class Dense:
        def __init__(self): self.calls = []
        async def search(self, space_id, vector, k=50):
            self.calls.append(vector)
            if vector == [2.0]:
                return [ScoredChunk(chunk_id='expansion-only', paper_id='p', text='semantic expansion hit')]
            return [ScoredChunk(chunk_id='original', paper_id='p', text='original question')]

    class Sparse:
        async def search(self, query, space_id, k=50):
            return []

    async def embedder(texts):
        assert texts == ['question', 'expanded concept']
        return [[1.0], [2.0]]

    dense = Dense()
    result = await HybridRetriever(dense=dense, sparse=Sparse(), embedder=embedder).retrieve('space', 'question', extra_queries=['expanded concept'])
    assert dense.calls == [[1.0], [2.0]]
    assert 'expansion-only' in [chunk.chunk_id for chunk in result.chunks]
