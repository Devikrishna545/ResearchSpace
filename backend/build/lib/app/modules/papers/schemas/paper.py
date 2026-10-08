from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4
from pydantic import BaseModel, Field
class IdentifierType(StrEnum): DOI='doi'; ARXIV='arxiv'; PMID='pmid'; OPENALEX='openalex'; TITLE='title'
class PaperIdentifier(BaseModel): type:IdentifierType; value:str
class Paper(BaseModel):
    id:str=Field(default_factory=lambda: str(uuid4())); doi:str|None=None; arxiv_id:str|None=None; pmid:str|None=None; openalex_id:str|None=None
    title:str; authors:list[str]=Field(default_factory=list); year:int|None=None; venue:str|None=None; abstract:str|None=None
    citation_count:int=0; oa_status:str|None=None; pdf_url:str|None=None; source:str|None=None; raw_payload:dict[str,Any]=Field(default_factory=dict)
class RawPaperRecord(BaseModel):
    source:str; title:str; authors:list[str]=Field(default_factory=list); year:int|None=None; venue:str|None=None; abstract:str|None=None
    doi:str|None=None; arxiv_id:str|None=None; pmid:str|None=None; openalex_id:str|None=None; citation_count:int=0; oa_status:str|None=None; pdf_url:str|None=None; url:str|None=None; raw_payload:dict[str,Any]=Field(default_factory=dict)
class IngestStatus(StrEnum): QUEUED='QUEUED'; FETCHING='FETCHING'; PARSING='PARSING'; CHUNKING='CHUNKING'; EMBEDDING='EMBEDDING'; PROFILING='PROFILING'; READY='READY'; FAILED='FAILED'; DEGRADED='DEGRADED'
class IngestJob(BaseModel): job_id:str; paper_id:str; status:IngestStatus; message:str|None=None; created_at:datetime|None=None
