from pydantic import BaseModel, Field
from app.shared.schemas.common import SourceHealth
class SearchFilters(BaseModel):
    year_min:int|None=None; year_max:int|None=None; sources:list[str]=Field(default_factory=list); open_access_only:bool=False; venue:str|None=None; author:str|None=None; min_citations:int|None=None
class SearchQuery(BaseModel):
    query:str; filters:SearchFilters=Field(default_factory=SearchFilters); limit:int=Field(default=20,ge=1,le=100)
    include_web:bool=False; domain_tags:list[str]=Field(default_factory=list); arxiv_categories:list[str]=Field(default_factory=list); query_terms:list[str]=Field(default_factory=list)
class SearchPlan(BaseModel):
    topic:str; sub_queries:list[str]; source_hints:list[str]=Field(default_factory=list); filters:SearchFilters=Field(default_factory=SearchFilters)
    limit:int=20; include_web:bool=False; domain_tags:list[str]=Field(default_factory=list); arxiv_categories:list[str]=Field(default_factory=list); query_terms:list[str]=Field(default_factory=list)
class RankedPaper(BaseModel): paper:'Paper'; score:float=0.0; rank_explanation:str|None=None
class RankedPaperList(BaseModel):
    results:list[RankedPaper]
    web_results:list[RankedPaper]=Field(default_factory=list)
    source_health:list[SourceHealth]=Field(default_factory=list)
from app.modules.papers.schemas.paper import Paper
RankedPaper.model_rebuild()
