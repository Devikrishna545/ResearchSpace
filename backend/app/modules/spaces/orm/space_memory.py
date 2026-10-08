from datetime import datetime
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import String,Text,JSON,DateTime,ForeignKey
from app.db.base import Base, utcnow
class SpaceMemory(Base):
    __tablename__='space_memory'; space_id:Mapped[str]=mapped_column(String,ForeignKey('research_spaces.id'),primary_key=True); rolling_summary:Mapped[str|None]=mapped_column(Text,nullable=True); findings:Mapped[list]=mapped_column(JSON,default=list); open_questions:Mapped[list]=mapped_column(JSON,default=list); updated_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=utcnow,onupdate=utcnow)
