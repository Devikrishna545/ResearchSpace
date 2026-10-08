from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, utcnow


class LegacyClaimAudit(Base):
    __tablename__ = "legacy_claim_audits"

    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), primary_key=True)
    foreign_key_violations: Mapped[list] = mapped_column(JSON, nullable=False)
    comparison_orphans: Mapped[list] = mapped_column(JSON, nullable=False)
    unreferenced_paper_ids: Mapped[list] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
