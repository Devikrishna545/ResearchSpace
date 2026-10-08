from datetime import datetime
from pydantic import BaseModel, Field


class SpaceCreate(BaseModel):
    name: str


class SpaceUpdate(BaseModel):
    name: str = Field(min_length=1)


class SpaceDuplicateRequest(BaseModel):
    copy_notes: bool = False
    name: str | None = None


class SearchHit(BaseModel):
    type: str
    id: str
    snippet: str
    created_at: str


class ResearchSpaceDTO(BaseModel):
    id: str | None = None
    name: str
    status: str = 'active'
    pin_count: int = 0
    created_at: datetime | None = None
    updated_at: datetime | None = None

