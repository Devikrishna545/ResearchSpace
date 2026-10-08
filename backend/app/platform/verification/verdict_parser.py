import re
from app.core.exceptions import VerdictParseError
from app.platform.verification.schemas import ReviewVerdict
from app.platform.llm.model_json import extract_json as _extract_json
from app.platform.llm.model_json import field, list_items
class VerdictParser:
    def parse(self,text:str)->ReviewVerdict:
        try:
            return ReviewVerdict.model_validate(self._normalize(_extract_json(text)))
        except (ValueError, TypeError) as exc:
            raise VerdictParseError(f'Could not parse reviewer verdict: {exc}') from exc
    def _normalize(self,obj):
        if isinstance(obj,dict):
            wrapped=field(obj,'output','result','data')
            if isinstance(wrapped,dict) and field(obj,'verdict') is None: obj=wrapped
            obj={str(k).lower():v for k,v in obj.items()}
            if isinstance(obj.get('verdict'),str):
                v=obj['verdict'].upper().replace(' ','_')
                if v not in {'APPROVED','REVISE','EVIDENCE_GAP','REJECT'}:
                    # Models sometimes echo the "A | B" schema example; take the first valid token.
                    for tok in ('APPROVED','REVISE','EVIDENCE_GAP','REJECT'):
                        if tok in v: v=tok; break
                obj['verdict']=v
            if 'overall_score' in obj:
                try: obj['overall_score']=max(0.0,min(1.0,float(obj['overall_score'])))
                except (TypeError,ValueError): pass
            claims=[]
            for cl in list_items(obj,'claims',aliases=('claim',),text_key='claim_text'):
                cl={str(k).lower():v for k,v in cl.items()}
                if isinstance(cl.get('status'),str): cl['status']=cl['status'].upper()
                if 'claim_id' in cl and 'status' in cl:
                    claims.append(cl)
                elif cl:
                    raise ValueError('Reviewer claim lacks an explicit claim_id or status')
            obj['claims']=claims
        return obj
    def _extract_object(self,text):
        s=text.find('{'); e=text.rfind('}'); return text[s:e+1] if s!=-1 and e>s else None
    def _repair(self,text): return re.sub(r',\s*([}\]])',r'\1',text.strip())
