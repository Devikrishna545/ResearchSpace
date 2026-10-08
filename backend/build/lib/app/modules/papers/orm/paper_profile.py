from datetime import datetime
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import String,Text,DateTime,Boolean,ForeignKey
from app.db.base import Base, utcnow
class PaperProfile(Base):
    __tablename__='paper_profiles'; id:Mapped[str]=mapped_column(String,primary_key=True); paper_id:Mapped[str]=mapped_column(String,ForeignKey('papers.id'),unique=True); problem:Mapped[str|None]=mapped_column(Text,nullable=True); method:Mapped[str|None]=mapped_column(Text,nullable=True); dataset:Mapped[str|None]=mapped_column(Text,nullable=True); metrics:Mapped[str|None]=mapped_column(Text,nullable=True); results:Mapped[str|None]=mapped_column(Text,nullable=True); limitations:Mapped[str|None]=mapped_column(Text,nullable=True); future_work:Mapped[str|None]=mapped_column(Text,nullable=True); generated_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=utcnow); verified:Mapped[bool]=mapped_column(Boolean,default=False)
