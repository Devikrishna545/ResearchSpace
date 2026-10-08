from typing import Literal

from pydantic import BaseModel, Field, field_validator

MAX_TITLE_LENGTH = 200
MAX_MENTIONS = 5


def _clean_title(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = " ".join(value.split())
    if not cleaned:
        raise ValueError("title must contain visible text")
    return cleaned


class ChatSessionCreate(BaseModel):
    title: str | None = Field(default=None, max_length=MAX_TITLE_LENGTH)

    @field_validator("title")
    @classmethod
    def clean_title(cls, value: str | None) -> str | None:
        return _clean_title(value)


class ChatSessionUpdate(BaseModel):
    title: str | None = Field(default=None, max_length=MAX_TITLE_LENGTH)
    pinned: bool | None = None
    archived: bool | None = None

    @field_validator("title")
    @classmethod
    def clean_title(cls, value: str | None) -> str | None:
        return _clean_title(value)


ChatSessionStatus = Literal["active", "archived", "all"]


class ChatRequest(BaseModel):
    question: str
    session_id: str | None = None
    mentioned_session_ids: list[str] = Field(default_factory=list, max_length=MAX_MENTIONS)
