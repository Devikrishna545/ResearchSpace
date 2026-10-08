import os
from functools import lru_cache
from pathlib import Path
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict
class Settings(BaseSettings):
    model_config=SettingsConfigDict(env_file='.env',env_file_encoding='utf-8',extra='ignore')
    app_name:str='R.Space'; app_env:str='development'
    database_url:str='sqlite+aiosqlite:///./data/dev.db'
    upload_dir:Path=Field(default_factory=lambda: Path(os.environ.get('LOCALAPPDATA') or Path.home()/'.local'/'share')/'R.Space'/'uploads')
    qdrant_url:str|None='http://localhost:6333'; redis_url:str|None='redis://localhost:6379/0'; grobid_url:str|None='http://localhost:8070'
    ollama_base_url:str='http://localhost:11434'; ollama_keep_alive:str='10m'; ollama_timeout_s:float=15.0; ollama_num_ctx:int=8192
    ollama_model_small:str='llama3.2:3b'; ollama_model_medium:str='llama3.1:8b'; ollama_model_large:str='llama3.1:8b'; ollama_model_verify:str='llama3.1:8b'; ollama_model_embed:str='nomic-embed-text'
    loop_max_iterations:int=Field(default=3,ge=1,le=5); loop_wall_clock_cap_ms:int=Field(default=20000,ge=1000); loop_acceptance_threshold:float=Field(default=0.90,ge=0,le=1)
    # Grounded compare. Tags are pinned explicitly; never rely on ":latest" for reproducible output.
    grounded_tier:str=Field(default='student',pattern='^(weak|student|deep)$')
    grounded_text_model:str='qwen3:8b'; grounded_vision_model:str='qwen3-vl:8b-instruct'; grounded_embed_model:str='embeddinggemma:300m-qat-q4_0'
    grounded_weak_text_model:str='qwen3:4b'; grounded_weak_vision_model:str='qwen3-vl:4b-instruct'
    grounded_deep_text_model:str='qwen3:30b-thinking'; grounded_deep_vision_model:str='qwen3-vl:32b-thinking'; grounded_deep_alt_model:str='mistral-small3.1:24b'
    grounded_seed:int=42; grounded_num_ctx:int=Field(default=16384,ge=2048)
    grounded_llm_timeout_s:float=Field(default=300.0,gt=0)
    grounded_retrieval_k:int=Field(default=8,ge=1,le=40)
    grounded_max_vlm_pages:int=Field(default=12,ge=0,le=200)
    grounded_novelty_min_corpus:int=Field(default=20,ge=1)
    grounded_novelty_top_k:int=Field(default=30,ge=5,le=50)
    semantic_scholar_api_key:str|None=None; core_api_key:str|None=None; pubmed_api_key:str|None=None; unpaywall_email:str|None=None
    web_search_provider:str='duckduckgo'; brave_api_key:str|None=None; tavily_api_key:str|None=None; searxng_url:str|None=None
    source_user_agent:str='research-assistant/0.1'
    source_contact_email:str|None=None
    source_timeout_s:float=Field(default=12.0,gt=0)
    source_cache_ttl_s:int=Field(default=900,ge=1)
    source_cache_max_entries:int=Field(default=256,ge=1)
    source_cache_max_bytes:int=Field(default=32*1024*1024,ge=1024)
    ranking_recency_weight:float=Field(default=0.0,ge=0.0,le=0.06)
    ranking_remove_stopwords:bool=False
    cors_allow_origins:list[str]=['http://localhost:3000','http://127.0.0.1:3000']
    cookie_secure:bool=False
    linkedin_client_id:str|None=None
    linkedin_client_secret:str|None=None
    linkedin_redirect_uri:str|None=None
    linkedin_token_key:str|None=None
    linkedin_member_social_enabled:bool=False
    linkedin_api_version:str='202609'
@lru_cache
def get_settings()->Settings:
    settings=Settings()
    # Ensure the local sqlite data directory exists for the dev fallback DB.
    if settings.database_url.startswith('sqlite'):
        Path('./data').mkdir(parents=True, exist_ok=True)
    return settings
