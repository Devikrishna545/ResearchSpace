from app.shared.text import tokenize
class MMR:
    def diversify(self,chunks,top_k:int=8):
        selected=[]; remaining=chunks[:]
        while remaining and len(selected)<top_k:
            def novelty(c):
                terms=set(tokenize(c.text))
                if not selected: return c.score
                sim=max(len(terms & set(tokenize(s.text)))/max(1,len(terms | set(tokenize(s.text)))) for s in selected)
                return 0.7*c.score-0.3*sim
            pick=max(remaining,key=novelty); selected.append(pick); remaining.remove(pick)
        return selected
