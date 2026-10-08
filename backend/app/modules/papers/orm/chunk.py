from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import String,Integer,Text,ForeignKey,JSON
from app.db.base import Base
class Chunk(Base):
    __tablename__='chunks'; id:Mapped[str]=mapped_column(String,primary_key=True); paper_id:Mapped[str]=mapped_column(String,ForeignKey('papers.id')); section:Mapped[str|None]=mapped_column(String,nullable=True); page:Mapped[int|None]=mapped_column(Integer,nullable=True); ordinal:Mapped[int]=mapped_column(Integer,default=0); text:Mapped[str]=mapped_column(Text); token_count:Mapped[int]=mapped_column(Integer,default=0); vector_id:Mapped[str|None]=mapped_column(String,nullable=True); embedding_json:Mapped[list|None]=mapped_column(JSON,nullable=True)
