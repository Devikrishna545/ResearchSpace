

def test_context_builder_bounds_prompt_size():
    """Regression: oversized evidence overflowed num_ctx and produced empty drafts."""
    from app.platform.retrieval.context_builder import ContextBuilder
    from app.modules.chat.schemas.chat import ScoredChunk
    chunks = [ScoredChunk(chunk_id=f'c{i}', text=' '.join(['word'] * 500)) for i in range(20)]
    ev = ContextBuilder().pack(chunks, 'q')
    assert len(ev.chunks) <= 8
    assert sum(len(c.text.split()) for c in ev.chunks) <= 1800 + 500


def test_context_builder_always_keeps_at_least_one_chunk():
    from app.platform.retrieval.context_builder import ContextBuilder
    from app.modules.chat.schemas.chat import ScoredChunk
    huge = ScoredChunk(chunk_id='big', text=' '.join(['word'] * 9000))
    ev = ContextBuilder().pack([huge], 'q')
    assert [c.chunk_id for c in ev.chunks] == ['big']


async def test_explicit_paper_title_outranks_generic_keyword_overlap():
    from app.platform.retrieval.reranker import Reranker
    from app.modules.chat.schemas.chat import ScoredChunk
    chunks = [
        ScoredChunk(chunk_id="generic", source="Quantum Programming Without the Quantum Physics",
                    text="What is quantum programming? Tensor techniques are mentioned.", score=0.03),
        ScoredChunk(chunk_id="target", source="Tensor quantum programming",
                    text="Running algorithms involves complex circuits and tensor networks.", score=0.02),
    ]
    ranked = await Reranker().rerank("what is tensor quantum programming", chunks)
    assert ranked[0].chunk_id == "target"


async def test_named_paper_definition_does_not_mix_other_papers():
    from app.platform.retrieval.hybrid_retriever import HybridRetriever
    from app.platform.retrieval.sparse_search import SparseSearch
    from app.modules.chat.schemas.chat import ScoredChunk
    chunks = [
        ScoredChunk(chunk_id="target", paper_id="p1", source="Tensor quantum programming",
                    text="An algorithm encodes matrix product operators as quantum circuits."),
        ScoredChunk(chunk_id="other", paper_id="p2", source="Quantum Programming Without the Quantum Physics",
                    text="What is quantum programming? A different method."),
    ]
    retriever = HybridRetriever(sparse=SparseSearch(chunks))
    evidence = await retriever.retrieve("space", "what is tensor quantum programming", extra_queries=["quantum programming"])
    assert [c.chunk_id for c in evidence.chunks] == ["target"]
    comparison = await retriever.retrieve("space", "Compare Tensor quantum programming with Quantum Programming Without the Quantum Physics")
    assert {c.paper_id for c in comparison.chunks} == {"p1", "p2"}
    scoped = await retriever.retrieve("space", "quantum programming", scope=["p2"])
    assert {c.paper_id for c in scoped.chunks} == {"p2"}
    empty = await retriever.retrieve("space", "quantum programming", scope=[])
    assert not empty.chunks
