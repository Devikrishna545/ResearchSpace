from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import String,Integer,Text,ForeignKey,Float
from app.db.base import Base
class Citation(Base):
    __tablename__='citations'; id:Mapped[str]=mapped_column(String,primary_key=True); turn_id:Mapped[str]=mapped_column(String,ForeignKey('turns.id')); chunk_id:Mapped[str]=mapped_column(String,ForeignKey('chunks.id')); paper_id:Mapped[str|None]=mapped_column(String,nullable=True); section:Mapped[str|None]=mapped_column(String,nullable=True); page:Mapped[int|None]=mapped_column(Integer,nullable=True); quote:Mapped[str|None]=mapped_column(Text,nullable=True); claim_text:Mapped[str|None]=mapped_column(Text,nullable=True); match_score:Mapped[float|None]=mapped_column(Float,nullable=True); ordinal:Mapped[int]=mapped_column(Integer,default=0)
