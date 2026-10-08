from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class LinkedInOAuthState(Base):
    __tablename__ = "linkedin_oauth_states"

    state_hash: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False)
    session_hash: Mapped[str] = mapped_column(String, ForeignKey("auth_sessions.token_hash", ondelete="CASCADE"), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class LinkedInConnection(Base):
    __tablename__ = "linkedin_connections"

    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), primary_key=True)
    encrypted_token: Mapped[str] = mapped_column(Text, nullable=False)
    member_id: Mapped[str] = mapped_column(String, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class LinkedInPostAttempt(Base):
    __tablename__ = "linkedin_post_attempts"
    __table_args__ = (UniqueConstraint("user_id", "request_id", name="uq_linkedin_post_request"),)

    id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False)
    request_id: Mapped[str] = mapped_column(String, nullable=False)
    source_type: Mapped[str] = mapped_column(String, nullable=False)
    source_id: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    result_urn: Mapped[str | None] = mapped_column(String, nullable=True)
