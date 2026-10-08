class VectorIndexer:
    def __init__(self,store): self.store=store
    async def index(self,space_id,chunks,vectors): await self.store.upsert(space_id,chunks,vectors)
