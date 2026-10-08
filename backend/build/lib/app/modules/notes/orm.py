from datetime import datetime
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import String,Text,DateTime,ForeignKey,Integer
from app.db.base import Base, utcnow
class Note(Base):
    __tablename__='notes'; id:Mapped[str]=mapped_column(String,primary_key=True); space_id:Mapped[str]=mapped_column(String,ForeignKey('research_spaces.id')); paper_id:Mapped[str|None]=mapped_column(String,ForeignKey('papers.id'),nullable=True); content:Mapped[str]=mapped_column(Text); source:Mapped[str]=mapped_column(String,default='manual'); chunk_id:Mapped[str|None]=mapped_column(String,ForeignKey('chunks.id'),nullable=True); anchor_quote:Mapped[str|None]=mapped_column(Text,nullable=True); anchor_start:Mapped[int|None]=mapped_column(Integer,nullable=True); anchor_end:Mapped[int|None]=mapped_column(Integer,nullable=True); color:Mapped[str|None]=mapped_column(String,nullable=True); created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=utcnow); updated_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=utcnow,onupdate=utcnow)
