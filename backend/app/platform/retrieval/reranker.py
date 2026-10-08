from app.shared.text import normalize_title, tokenize
class Reranker:
    async def rerank(self,question,chunks,top_k:int=12):
        q=set(tokenize(question)); rescored=[]
        normalized_question=' '+normalize_title(question)+' '
        for c in chunks:
            title=normalize_title(c.source or '')
            title_match=len(title.split())>=2 and ' '+title+' ' in normalized_question
            overlap=len(q.intersection(tokenize(c.text)))/max(1,len(q))
            rescored.append(c.model_copy(update={'score':c.score+overlap+(2.0 if title_match else 0.0)}))
        return sorted(rescored,key=lambda c:c.score,reverse=True)[:top_k]
