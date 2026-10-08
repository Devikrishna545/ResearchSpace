import re
from app.platform.llm.model_router import ModelTier
from app.platform.llm.prompts.loader import PromptLoader
from app.modules.chat.schemas.chat import Claim,Draft,EvidenceSet

class AnswerAgent:
    name='answer_agent'
    def __init__(self,llm=None,router=None,prompts:PromptLoader|None=None): self.llm=llm; self.router=router; self.prompts=prompts or PromptLoader()
    async def generate(self,question:str,evidence:EvidenceSet,feedback_history=None)->Draft:
        if self.llm and self.router:
            system=self.prompts.render('answer_agent/system.jinja')
            user=self.prompts.render('answer_agent/user.jinja',question=question,evidence=evidence,feedback_history=feedback_history or [])
            text=await self.llm.chat([{'role':'system','content':system},{'role':'user','content':user}],self.router.model_for(ModelTier.MEDIUM),temperature=0.3)
        elif not evidence.chunks: text='Not supported by the attached papers.'
        else:
            citations=' '.join(f'[{c.chunk_id}]' for c in evidence.chunks[:2]); feedback=' '.join(v.global_feedback for v in (feedback_history or []) if v.global_feedback)
            text=f'Based on the attached evidence, {question.rstrip("?")} is addressed by the cited passages {citations}. {feedback}'.strip()
        claims=[Claim(claim_id=f'c{i+1}',text=s.strip(),cited_chunk_ids=re.findall(r'\[([^\]]+)\]',s)) for i,s in enumerate(re.split(r'(?<=[.!?])\s+',text)) if s.strip()]
        return Draft(text=text,claims=claims)
