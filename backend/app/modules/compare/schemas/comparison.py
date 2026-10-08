from datetime import datetime

from pydantic import BaseModel, Field

GROUNDED_REPORT_KIND = "grounded"
LEGACY_REPORT_KIND = "legacy_profile"
LEGACY_REPORT_GONE = (
    "This is a retired profile-only comparison: it compared generated profiles, not source evidence. "
    "Run a grounded comparison instead."
)


class ComparisonReportSummary(BaseModel):
    id: str
    paper_ids: list[str] = Field(default_factory=list)
    generated_at: datetime
    report_kind: str = GROUNDED_REPORT_KIND
