from pydantic import BaseModel, Field


class WebCaptureRequest(BaseModel):
    url: str
    title: str | None = None
    content: str | None = Field(default=None, description="Optional user-selected page text.")
