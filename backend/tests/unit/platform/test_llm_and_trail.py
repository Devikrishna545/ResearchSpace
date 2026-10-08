import pytest

from app.core.config import Settings
from app.platform.llm.ollama_client import OllamaClient
from app.platform.verification.trail import VerificationTrail

class Response:
    def __init__(self, payload): self.payload = payload
    def raise_for_status(self): pass
    def json(self): return self.payload

class FakeClient:
    def __init__(self): self.payloads = []
    async def post(self, url, json):
        self.payloads.append(json)
        inputs = json['input']
        assert isinstance(inputs, list)
        return Response({'embeddings': [[float(value)] for value in inputs]})

@pytest.mark.asyncio
async def test_ollama_embed_batches_and_preserves_order():
    client = FakeClient()
    ollama = OllamaClient(Settings(), client=client)
    result = await ollama.embed([str(i) for i in range(65)], 'embed-model')
    assert len(client.payloads) == 3
    assert [len(p['input']) for p in client.payloads] == [32, 32, 1]
    assert result[:3] == [[0.0], [1.0], [2.0]]
    assert result[-1] == [64.0]

def test_trail_memory_is_bounded():
    trail = VerificationTrail(max_memory=3)
    for i in range(5):
        trail._remember(f'turn-{i}', [i])
    assert list(trail.memory) == ['turn-2', 'turn-3', 'turn-4']
