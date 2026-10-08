import json, httpx
from collections.abc import AsyncIterator
from functools import lru_cache
from app.core.config import Settings, get_settings
from app.core.exceptions import LLMUnavailableError
from app.platform.llm.provider import LLMProvider

class OllamaClient(LLMProvider):
    def __init__(self,settings:Settings,client:httpx.AsyncClient|None=None):
        self.settings=settings; self.base_url=settings.ollama_base_url.rstrip('/'); self._client=client; self._owns_client=client is None
    def _http(self)->httpx.AsyncClient:
        if self._client is None:
            self._client=httpx.AsyncClient(timeout=self.settings.ollama_timeout_s)
        return self._client
    async def aclose(self)->None:
        if self._client is not None and self._owns_client:
            await self._client.aclose(); self._client=None
    async def chat(self,messages:list[dict],model:str,temperature:float=0.0,json_format:bool=False,*,schema:dict|None=None,seed:int|None=None,think:bool|None=None,num_ctx:int|None=None,timeout:float|None=None,num_predict:int|None=None)->str:
        try:
            options={'temperature':temperature,'num_ctx':num_ctx or self.settings.ollama_num_ctx}
            if seed is not None: options['seed']=seed
            if num_predict is not None: options['num_predict']=num_predict
            payload={'model':model,'messages':messages,'stream':False,'keep_alive':self.settings.ollama_keep_alive,'options':options}
            if schema is not None: payload['format']=schema
            elif json_format: payload['format']='json'
            if think is not None: payload['think']=think
            extra={'timeout':timeout} if timeout is not None else {}
            r=await self._http().post(f'{self.base_url}/api/chat',json=payload,**extra); r.raise_for_status(); return r.json().get('message',{}).get('content','')
        except Exception as exc: raise LLMUnavailableError(f'Ollama chat unavailable: {exc}') from exc
    async def version(self)->str|None:
        try:
            r=await self._http().get(f'{self.base_url}/api/version'); r.raise_for_status(); return r.json().get('version')
        except Exception:
            return None
    async def model_digests(self)->dict[str,str]:
        """Installed model tag -> content digest, so artifacts record exactly which weights ran."""
        try:
            r=await self._http().get(f'{self.base_url}/api/tags'); r.raise_for_status()
            return {m.get('name') or m.get('model'):m.get('digest','') for m in r.json().get('models',[]) if m.get('name') or m.get('model')}
        except Exception:
            return {}
    async def chat_stream(self,messages:list[dict],model:str,temperature:float=0.0)->AsyncIterator[str]:
        try:
            async with self._http().stream('POST',f'{self.base_url}/api/chat',json={'model':model,'messages':messages,'stream':True,'keep_alive':self.settings.ollama_keep_alive,'options':{'temperature':temperature}}) as r:
                r.raise_for_status()
                async for line in r.aiter_lines():
                    if line: yield json.loads(line).get('message',{}).get('content','')
        except Exception as exc: raise LLMUnavailableError(f'Ollama stream unavailable: {exc}') from exc
    async def embed(self,texts:list[str],model:str)->list[list[float]]:
        out=[]
        try:
            client=self._http()
            for start in range(0,len(texts),32):
                batch=texts[start:start+32]
                data=await self._embed_batch(client,batch,model)
                out.extend(data)
            return out
        except Exception as exc: raise LLMUnavailableError(f'Ollama embed unavailable: {exc}') from exc
    async def _embed_batch(self,client:httpx.AsyncClient,texts:list[str],model:str)->list[list[float]]:
        r=await client.post(f'{self.base_url}/api/embed',json={'model':model,'input':texts,'keep_alive':self.settings.ollama_keep_alive}); r.raise_for_status(); data=r.json(); embeddings=data.get('embeddings')
        if isinstance(embeddings,list) and len(embeddings)==len(texts):
            return embeddings
        if len(texts)==1:
            emb=data.get('embedding')
            if isinstance(emb,list): return [emb]
        out=[]
        for text in texts:
            r=await client.post(f'{self.base_url}/api/embed',json={'model':model,'input':text,'keep_alive':self.settings.ollama_keep_alive}); r.raise_for_status(); data=r.json(); emb=data.get('embeddings') or []; out.append(emb[0] if emb else data.get('embedding',[]))
        return out

@lru_cache(maxsize=1)
def get_ollama_client()->OllamaClient:
    return OllamaClient(get_settings())

async def close_shared_ollama_client()->None:
    client=get_ollama_client()
    await client.aclose()
    get_ollama_client.cache_clear()
