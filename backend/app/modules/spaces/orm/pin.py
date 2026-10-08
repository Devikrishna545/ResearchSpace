from datetime import datetime
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import String,DateTime,ForeignKey,UniqueConstraint
from app.db.base import Base, utcnow
class Pin(Base):
    __tablename__='pins'; __table_args__=(UniqueConstraint('space_id','paper_id',name='uq_pin_space_paper'),)
    id:Mapped[str]=mapped_column(String,primary_key=True); space_id:Mapped[str]=mapped_column(String,ForeignKey('research_spaces.id')); paper_id:Mapped[str]=mapped_column(String,ForeignKey('papers.id')); pinned_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=utcnow)
