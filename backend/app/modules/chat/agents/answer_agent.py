import re
from pydantic import BaseModel, Field
from app.core.exceptions import DraftParseError
from app.platform.llm.model_router import ModelTier
from app.platform.llm.model_json import extract_json
from app.platform.llm.prompts.loader import PromptLoader
from app.modules.chat.schemas.chat import Claim,Draft,EvidenceSet


class _AnswerClaim(BaseModel):
    text: str = Field(min_length=1)
    cited_chunk_ids: list[str] = Field(min_length=1)


class _AnswerContent(BaseModel):
    claims: list[_AnswerClaim] = Field(max_length=5)


class AnswerAgent:
    name='answer_agent'
    def __init__(self,llm=None,router=None,prompts:PromptLoader|None=None): self.llm=llm; self.router=router; self.prompts=prompts or PromptLoader()
    async def generate(self,question:str,evidence:EvidenceSet,feedback_history=None)->Draft:
        if not evidence.chunks:
            return Draft(text='Not supported by the attached papers.')
        if self.llm and self.router:
            system=self.prompts.render('answer_agent/system.jinja')
            user=self.prompts.render('answer_agent/user.jinja',question=question,evidence=evidence,feedback_history=feedback_history or [])
            schema=_AnswerContent.model_json_schema()
            schema['$defs']['_AnswerClaim']['properties']['cited_chunk_ids']['items']['enum']=[c.chunk_id for c in evidence.chunks]
            raw=await self.llm.chat([{'role':'system','content':system},{'role':'user','content':user}],self.router.model_for(ModelTier.MEDIUM),temperature=0.0,json_format=True,schema=schema)
            try:
                content=_AnswerContent.model_validate(extract_json(raw))
            except ValueError as exc:
                raise DraftParseError('Answer output did not match the required claim format.') from exc
            claims=[]
            evidence_ids={c.chunk_id for c in evidence.chunks}
            for i,item in enumerate(content.claims):
                sentence=re.sub(r'\[[^\]]+\]','',item.text).strip().rstrip('.!?')
                if not sentence:
                    raise DraftParseError('Answer contained an empty claim.')
                ids=list(dict.fromkeys(item.cited_chunk_ids))
                if any(cid not in evidence_ids for cid in ids):
                    raise DraftParseError('Answer cited a chunk outside the retrieved evidence.')
                text=sentence+' '+ ' '.join(f'[{cid}]' for cid in ids)+'.'
                claims.append(Claim(claim_id=f'c{i+1}',text=text,cited_chunk_ids=ids))
            return Draft(text=' '.join(c.text for c in claims) or 'Not supported by the attached papers.',claims=claims)
        else:
            citations=' '.join(f'[{c.chunk_id}]' for c in evidence.chunks[:2]); feedback=' '.join(v.global_feedback for v in (feedback_history or []) if v.global_feedback)
            text=f'Based on the attached evidence, {question.rstrip("?")} is addressed by the cited passages {citations}. {feedback}'.strip()
        claims=[Claim(claim_id=f'c{i+1}',text=s.strip(),cited_chunk_ids=re.findall(r'\[([^\]]+)\]',s)) for i,s in enumerate(re.split(r'(?<=[.!?])\s+',text)) if s.strip()]
        return Draft(text=text,claims=claims)
