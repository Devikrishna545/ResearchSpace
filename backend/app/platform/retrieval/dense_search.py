class DenseSearch:
    def __init__(self,store): self.store=store
    async def search(self,query_vector:list[float],space_id:str,k:int=50): return await self.store.search(space_id,query_vector,k)
