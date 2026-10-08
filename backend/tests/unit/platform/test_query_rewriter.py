import pytest
from types import SimpleNamespace

from app.core.exceptions import LLMUnavailableError
from app.platform.retrieval.query_rewriter import QueryRewriter


class _LLM:
    def __init__(self, reply): self.reply = reply; self.messages = []
    async def chat(self, messages, model, temperature=0.0, json_format=False):
        self.messages.append(messages); return self.reply
class _Boom:
    async def chat(self, *a, **k): raise LLMUnavailableError('down')
class _Router:
    def model_for(self, tier): return 'small'


def _ctx():
    return SimpleNamespace(
        recent_turns=[SimpleNamespace(role='user', content='What does the MultiRAG paper propose?'),
                      SimpleNamespace(role='assistant', content='MultiRAG uses a knowledge construction module.')],
        rolling_summary='x' * 5000,
    )


async def test_rewrite_resolves_pronoun_to_standalone_question():
    llm = _LLM('What datasets was MultiRAG evaluated on?')
    out = await QueryRewriter(llm=llm, router=_Router()).rewrite('What datasets did they evaluate it on?', _ctx())
    assert out[0] == 'What datasets was MultiRAG evaluated on?'
    assert out[1] == 'What datasets did they evaluate it on?'


async def test_rewrite_query_stays_short_and_excludes_memory_blob():
    """Regression: the rewriter must not stuff the whole conversation into the query."""
    llm = _LLM('What datasets was MultiRAG evaluated on?')
    out = await QueryRewriter(llm=llm, router=_Router()).rewrite('What datasets did they evaluate it on?', _ctx())
    assert all(len(q) < 200 for q in out)
    sent = llm.messages[0][1]['content']
    assert 'x' * 100 not in sent  # rolling summary blob never reaches the prompt


async def test_rewrite_skipped_without_referential_terms():
    llm = _LLM('should not be called')
    out = await QueryRewriter(llm=llm, router=_Router()).rewrite('What datasets did MultiRAG use?', _ctx())
    assert out == ['What datasets did MultiRAG use?']
    assert llm.messages == []


async def test_rewrite_falls_back_when_model_unavailable():
    out = await QueryRewriter(llm=_Boom(), router=_Router()).rewrite('What did they do?', _ctx())
    assert out == ['What did they do?']


async def test_rewrite_strips_model_preamble():
    llm = _LLM('Rewritten: "What datasets was MultiRAG evaluated on?"\nextra junk')
    out = await QueryRewriter(llm=llm, router=_Router()).rewrite('What about it?', _ctx())
    assert out[0] == 'What datasets was MultiRAG evaluated on?'
