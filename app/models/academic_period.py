from datetime import date as _date
from sqlalchemy import Column, Integer, String, Boolean, Date, DateTime, Text, ForeignKey, Enum as SAEnum, UniqueConstraint
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import enum
from app.database import Base


class SemesterType(str, enum.Enum):
    first  = "first"   # 1st Semester
    second = "second"  # 2nd Semester
    summer = "summer"  # Summer Term


class AcademicPeriod(Base):
    __tablename__ = "academic_periods"

    id            = Column(Integer, primary_key=True, index=True)
    academic_year = Column(String, nullable=False)              # e.g. "2024-2025"
    semester      = Column(SAEnum(SemesterType), nullable=False)
    start_date    = Column(Date, nullable=False)
    end_date      = Column(Date, nullable=False)
    counts_toward_max = Column(Boolean, nullable=False, default=True)  # False for summer
    created_at    = Column(DateTime(timezone=True), server_default=func.now())

    gwa_submissions = relationship("GwaSubmission", back_populates="period", cascade="all, delete-orphan")

    __table_args__ = (UniqueConstraint("academic_year", "semester", name="uq_period_year_sem"),)

    @property
    def is_active(self) -> bool:
        today = _date.today()
        return self.start_date <= today <= self.end_date

    @property
    def is_ended(self) -> bool:
        return _date.today() > self.end_date

    @property
    def label(self) -> str:
        sem_label = {"first": "1st Sem", "second": "2nd Sem", "summer": "Summer"}
        return f"{sem_label.get(self.semester, self.semester)} · AY {self.academic_year}"


class GwaSubmissionStatus(str, enum.Enum):
    pending  = "pending"
    approved = "approved"
    rejected = "rejected"


class GwaSubmission(Base):
    __tablename__ = "gwa_submissions"

    id           = Column(Integer, primary_key=True, index=True)
    scholar_id   = Column(Integer, ForeignKey("scholars.id"), nullable=False, index=True)
    period_id    = Column(Integer, ForeignKey("academic_periods.id"), nullable=False)
    declared_gwa = Column(String, nullable=True)       # student's self-reported GWA
    proof_path   = Column(String, nullable=False)       # uploaded grade slip file path
    has_grade_below_2_5 = Column(Boolean, nullable=False, default=False)
    status       = Column(SAEnum(GwaSubmissionStatus), nullable=False, default=GwaSubmissionStatus.pending)
    rejection_remarks = Column(Text, nullable=True)
    submitted_at = Column(DateTime(timezone=True), server_default=func.now())
    reviewed_at  = Column(DateTime(timezone=True), nullable=True)
    reviewed_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)

    scholar     = relationship("Scholar", back_populates="gwa_submissions")
    period      = relationship("AcademicPeriod", back_populates="gwa_submissions")
    reviewed_by = relationship("User", foreign_keys=[reviewed_by_id])

    __table_args__ = (UniqueConstraint("scholar_id", "period_id", name="uq_gwa_sub_scholar_period"),)
