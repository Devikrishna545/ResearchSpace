from datetime import datetime
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import String,Float,JSON,DateTime,ForeignKey
from app.db.base import Base, utcnow
class ComparisonReport(Base):
    __tablename__='comparison_reports'; id:Mapped[str]=mapped_column(String,primary_key=True); space_id:Mapped[str]=mapped_column(String,ForeignKey('research_spaces.id')); paper_ids:Mapped[list]=mapped_column(JSON,default=list); matrix:Mapped[dict]=mapped_column(JSON,default=dict); commonalities:Mapped[list]=mapped_column(JSON,default=list); contradictions:Mapped[list]=mapped_column(JSON,default=list); gaps:Mapped[list]=mapped_column(JSON,default=list); confidence:Mapped[float]=mapped_column(Float,default=0.0); generated_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=utcnow)
    # Historical profile-only reports stay immutable and are labelled legacy; grounded
    # reports keep their full evidence snapshot in report_json.
    report_kind:Mapped[str]=mapped_column(String,nullable=False,default='legacy_profile',server_default='legacy_profile')
    report_json:Mapped[dict|None]=mapped_column(JSON,nullable=True)
    job_id:Mapped[str|None]=mapped_column(String,nullable=True)
