from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import String, Boolean
from app.db.base import Base, TimestampMixin
class User(Base,TimestampMixin):
    __tablename__='users'; id:Mapped[str]=mapped_column(String,primary_key=True); email:Mapped[str]=mapped_column(String,unique=True,index=True); password_hash:Mapped[str|None]=mapped_column(String,nullable=True); is_admin:Mapped[bool]=mapped_column(Boolean,default=False,nullable=False)
