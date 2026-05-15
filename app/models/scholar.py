from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime, ForeignKey, Enum as SAEnum
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import enum
from app.database import Base


class ScholarStatus(str, enum.Enum):
    active = "active"
    probationary = "probationary"
    under_review = "under_review"   # flagged for policy concern, pending OSFA decision
    on_leave = "on_leave"           # approved temporary suspension (medical, LOA)
    suspended = "suspended"         # university-imposed suspension
    terminated = "terminated"
    graduated = "graduated"


# Terminal states — no further transitions allowed
_TERMINAL = {ScholarStatus.terminated, ScholarStatus.graduated}

SCHOLAR_STATUS_TRANSITIONS: dict[ScholarStatus, list[ScholarStatus]] = {
    ScholarStatus.active: [
        ScholarStatus.probationary, ScholarStatus.under_review,
        ScholarStatus.on_leave, ScholarStatus.terminated, ScholarStatus.graduated,
    ],
    ScholarStatus.probationary: [
        ScholarStatus.active, ScholarStatus.under_review,
        ScholarStatus.on_leave, ScholarStatus.terminated,
    ],
    ScholarStatus.under_review: [
        ScholarStatus.active, ScholarStatus.probationary,
        ScholarStatus.on_leave, ScholarStatus.terminated,
    ],
    ScholarStatus.on_leave: [ScholarStatus.active, ScholarStatus.terminated],
    ScholarStatus.suspended: [ScholarStatus.active, ScholarStatus.terminated],
    ScholarStatus.terminated: [],
    ScholarStatus.graduated: [],
}


class Scholar(Base):
    __tablename__ = "scholars"

    id = Column(Integer, primary_key=True, index=True)
    application_id = Column(Integer, ForeignKey("applications.id"), unique=True, nullable=False)
    student_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    scholarship_id = Column(Integer, ForeignKey("scholarships.id"), nullable=False)
    status = Column(SAEnum(ScholarStatus), nullable=False, default=ScholarStatus.active)
    is_graduating = Column(Boolean, default=False)
    expected_graduation = Column(String)
    # Allowance tracking
    allowance_status   = Column(String, nullable=False, default="pending")  # pending | partial | released
    amount_released    = Column(Integer, nullable=True)
    last_release_date  = Column(DateTime(timezone=True), nullable=True)
    next_release_date  = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    application  = relationship("Application", back_populates="scholar")
    user         = relationship("User",         foreign_keys=[student_id])
    scholarship  = relationship("Scholarship",  foreign_keys=[scholarship_id])
    semester_records = relationship("SemesterRecord", back_populates="scholar", cascade="all, delete-orphan")
    status_logs      = relationship("ScholarStatusLog", back_populates="scholar", order_by="ScholarStatusLog.created_at")


class SemesterRecord(Base):
    __tablename__ = "semester_records"

    id = Column(Integer, primary_key=True, index=True)
    scholar_id = Column(Integer, ForeignKey("scholars.id"), nullable=False)
    semester = Column(String, nullable=False)
    academic_year = Column(String, nullable=False)
    gwa = Column(String)
    has_grade_below_2_5 = Column(Boolean, nullable=False, default=False)
    is_enrolled = Column(Boolean, default=True)
    notes = Column(Text)
    # Benefit tracking
    benefit_released    = Column(Boolean, nullable=False, default=False)
    benefit_released_at = Column(DateTime(timezone=True), nullable=True)
    # Thank you letter (private scholarships only)
    thank_you_submitted    = Column(Boolean, nullable=False, default=False)
    thank_you_submitted_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    scholar = relationship("Scholar", back_populates="semester_records")


class ScholarStatusLog(Base):
    """Immutable audit trail for every Scholar.status transition."""
    __tablename__ = "scholar_status_logs"

    id          = Column(Integer, primary_key=True, index=True)
    scholar_id  = Column(Integer, ForeignKey("scholars.id"), nullable=False, index=True)
    from_status = Column(SAEnum(ScholarStatus), nullable=True)
    to_status   = Column(SAEnum(ScholarStatus), nullable=False)
    actor_id    = Column(Integer, ForeignKey("users.id"), nullable=True)
    reason      = Column(Text, nullable=True)
    created_at  = Column(DateTime(timezone=True), server_default=func.now())

    scholar = relationship("Scholar", back_populates="status_logs")
    actor   = relationship("User", foreign_keys=[actor_id])
