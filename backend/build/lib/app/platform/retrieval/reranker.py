from app.shared.text import tokenize
class Reranker:
    async def rerank(self,question,chunks,top_k:int=12):
        q=set(tokenize(question)); rescored=[]
        for c in chunks:
            overlap=len(q.intersection(tokenize(c.text)))/max(1,len(q)); rescored.append(c.model_copy(update={'score':c.score+overlap}))
        return sorted(rescored,key=lambda c:c.score,reverse=True)[:top_k]
