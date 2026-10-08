from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, utcnow


class OpenAlexConsent(Base):
    __tablename__ = "openalex_consents"
    __table_args__ = (CheckConstraint("state IN ('unset', 'granted', 'declined')", name="ck_openalex_consent_state"),)

    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), primary_key=True)
    state: Mapped[str] = mapped_column(String, nullable=False, default="unset")
    contact_email: Mapped[str | None] = mapped_column(String, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)
