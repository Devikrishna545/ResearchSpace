from datetime import datetime
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import JSON,String,Text,DateTime,ForeignKey
from app.db.base import Base, utcnow
class Turn(Base):
    __tablename__='turns'; id:Mapped[str]=mapped_column(String,primary_key=True); space_id:Mapped[str]=mapped_column(String,ForeignKey('research_spaces.id')); role:Mapped[str]=mapped_column(String); content:Mapped[str]=mapped_column(Text); created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=utcnow)
    # Nullable so turns written by older clients (no session) remain valid.
    session_id:Mapped[str|None]=mapped_column(String,ForeignKey('chat_sessions.id'),nullable=True,index=True)
    mentions:Mapped[list|None]=mapped_column(JSON,nullable=True)
    answer_metadata:Mapped[dict|None]=mapped_column(JSON,nullable=True)
