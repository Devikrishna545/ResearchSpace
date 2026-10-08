from pydantic import BaseModel, Field


class NoteDTO(BaseModel):
    id: str | None = None
    space_id: str | None = None
    paper_id: str | None = None
    content: str
    source: str = "manual"
    chunk_id: str | None = None
    anchor_quote: str | None = None
    anchor_start: int | None = None
    anchor_end: int | None = None
    color: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


class NoteCreate(BaseModel):
    paper_id: str | None = None
    content: str = ""
    chunk_id: str | None = None
    anchor_quote: str | None = None
    anchor_start: int | None = Field(default=None, ge=0)
    anchor_end: int | None = Field(default=None, ge=0)
    color: str | None = None


class NoteUpdate(BaseModel):
    content: str = ""


class AutoNoteDTO(BaseModel):
    summary: str = ""
    key_contributions: list[str] = Field(default_factory=list)
    methodology: str = ""
    results: str = ""
    limitations: str = ""
    relevance: str = ""
