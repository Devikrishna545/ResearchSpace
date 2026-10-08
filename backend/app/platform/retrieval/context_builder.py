from app.modules.chat.schemas.chat import EvidenceSet


class ContextBuilder:
    """Packs retrieved chunks into an evidence set that fits the model context window.

    The budget is measured in words and deliberately conservative: prompt scaffolding,
    the system message, reviewer feedback and the generated answer all share num_ctx.
    Overflowing it makes Ollama truncate the prompt, the model loses its instructions
    and returns an empty completion, which the loop then has to abstain on.
    """

    def pack(self, chunks, query: str, word_budget: int = 1800, max_chunks: int = 8):
        total = 0
        packed = []
        for chunk in chunks:
            if len(packed) >= max_chunks:
                break
            words = len(chunk.text.split())
            if packed and total + words > word_budget:
                continue
            packed.append(chunk)
            total += words
        return EvidenceSet(chunks=packed, query=query)
