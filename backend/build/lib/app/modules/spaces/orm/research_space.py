from datetime import datetime
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import String, DateTime, ForeignKey
from app.db.base import Base, utcnow
class ResearchSpace(Base):
    __tablename__='research_spaces'; id:Mapped[str]=mapped_column(String,primary_key=True); user_id:Mapped[str|None]=mapped_column(String,ForeignKey('users.id'),nullable=True); name:Mapped[str]=mapped_column(String); status:Mapped[str]=mapped_column(String,default='active'); created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=utcnow); updated_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=utcnow,onupdate=utcnow)
