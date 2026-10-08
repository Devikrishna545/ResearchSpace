from enum import StrEnum
from pydantic import BaseModel
class HealthStatus(StrEnum): OK='ok'; DEGRADED='degraded'; UNAVAILABLE='unavailable'; RATE_LIMITED='rate_limited'
class SourceHealth(BaseModel):
    source:str; status:HealthStatus=HealthStatus.OK; latency_ms:int|None=None; error:str|None=None; retry_after_seconds:int|None=None; cached:bool=False
class ApiMessage(BaseModel): message:str
