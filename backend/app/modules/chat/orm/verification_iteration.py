from datetime import datetime
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import String,Integer,Float,Text,DateTime,JSON,ForeignKey
from app.db.base import Base, utcnow
class VerificationIteration(Base):
    __tablename__='verification_iterations'; id:Mapped[str]=mapped_column(String,primary_key=True); turn_id:Mapped[str]=mapped_column(String,ForeignKey('turns.id')); iteration:Mapped[int]=mapped_column(Integer); draft_text:Mapped[str]=mapped_column(Text); verdict:Mapped[str]=mapped_column(String); overall_score:Mapped[float]=mapped_column(Float); claim_findings:Mapped[list]=mapped_column(JSON,default=list); missing_evidence_queries:Mapped[list]=mapped_column(JSON,default=list); action_taken:Mapped[str]=mapped_column(String); latency_ms:Mapped[int]=mapped_column(Integer,default=0); model_used:Mapped[str|None]=mapped_column(String,nullable=True); created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=utcnow)
    verdict_json:Mapped[dict|None]=mapped_column(JSON,nullable=True)
