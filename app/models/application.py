from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, JSON, Enum as SAEnum
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import enum
from app.database import Base
from app.models.workflow import MainStatus, SubStatus


class ApplicationStatus(str, enum.Enum):
    """Legacy status — kept for backward compatibility."""
    pending    = "pending"
    approved   = "approved"
    rejected   = "rejected"
    incomplete = "incomplete"
    withdrawn  = "withdrawn"


class EvalStatus(str, enum.Enum):
    not_started = "not_started"
    in_review   = "in_review"
    completed   = "completed"


class Application(Base):
    __tablename__ = "applications"

    id            = Column(Integer, primary_key=True, index=True)
    student_id    = Column(Integer, ForeignKey("users.id"), nullable=False)
    scholarship_id = Column(Integer, ForeignKey("scholarships.id"), nullable=False)

    # ── Legacy (kept for backward compat) ────────────────────────────────────
    status        = Column(SAEnum(ApplicationStatus), nullable=False, default=ApplicationStatus.pending)
    eval_status   = Column(SAEnum(EvalStatus), nullable=False, default=EvalStatus.not_started)
    rejected_docs = Column(JSON, default=list)
    eval_score    = Column(JSON, nullable=True)
    remarks       = Column(Text)

    # ── New workflow columns ──────────────────────────────────────────────────
    main_status   = Column(SAEnum(MainStatus), nullable=True)
    sub_status    = Column(SAEnum(SubStatus),  nullable=True)

    # Timestamps per stage
    screened_at             = Column(DateTime(timezone=True), nullable=True)
    validated_at            = Column(DateTime(timezone=True), nullable=True)
    interview_scheduled_at  = Column(DateTime(timezone=True), nullable=True)
    interview_datetime      = Column(DateTime(timezone=True), nullable=True)  # actual slot
    interview_completed_at  = Column(DateTime(timezone=True), nullable=True)
    evaluated_at            = Column(DateTime(timezone=True), nullable=True)
    decision_released_at    = Column(DateTime(timezone=True), nullable=True)
    completion_submitted_at = Column(DateTime(timezone=True), nullable=True)
    closed_at               = Column(DateTime(timezone=True), nullable=True)

    # Interview metadata
    interview_location      = Column(String, nullable=True)
    interview_notes         = Column(Text, nullable=True)

    # Decision metadata
    decision_remarks        = Column(Text, nullable=True)

    submitted_at  = Column(DateTime(timezone=True), server_default=func.now())
    updated_at    = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # ── Relationships ─────────────────────────────────────────────────────────
    student       = relationship("User", back_populates="applications", foreign_keys=[student_id])
    scholarship   = relationship("Scholarship", back_populates="applications")
    documents     = relationship("ApplicationDocument", back_populates="application", cascade="all, delete-orphan")
    audit_entries = relationship("AuditEntry", back_populates="application", cascade="all, delete-orphan")
    appeal        = relationship("Appeal", back_populates="application", uselist=False, cascade="all, delete-orphan")
    scholar       = relationship("Scholar", back_populates="application", uselist=False, cascade="all, delete-orphan")
    workflow_logs = relationship("WorkflowLog", back_populates="application", cascade="all, delete-orphan", order_by="WorkflowLog.created_at")
    completion_requirements = relationship("CompletionRequirement", back_populates="application", cascade="all, delete-orphan")


class WorkflowLog(Base):
    """Full audit trail for every workflow transition."""
    __tablename__ = "workflow_logs"

    id              = Column(Integer, primary_key=True, index=True)
    application_id  = Column(Integer, ForeignKey("applications.id"), nullable=False)
    changed_by      = Column(Integer, ForeignKey("users.id"), nullable=False)
    from_main       = Column(SAEnum(MainStatus), nullable=True)
    from_sub        = Column(SAEnum(SubStatus),  nullable=True)
    to_main         = Column(SAEnum(MainStatus), nullable=False)
    to_sub          = Column(SAEnum(SubStatus),  nullable=False)
    note            = Column(Text, nullable=True)
    created_at      = Column(DateTime(timezone=True), server_default=func.now())

    application = relationship("Application", back_populates="workflow_logs")
    actor       = relationship("User", foreign_keys=[changed_by])


class CompletionRequirement(Base):
    """Post-approval documents submitted by student."""
    __tablename__ = "completion_requirements"

    id              = Column(Integer, primary_key=True, index=True)
    application_id  = Column(Integer, ForeignKey("applications.id"), nullable=False)
    requirement_type = Column(String, nullable=False)   # e.g. "thank_you_letter"
    file_url        = Column(String, nullable=True)
    submitted_at    = Column(DateTime(timezone=True), nullable=True)
    created_at      = Column(DateTime(timezone=True), server_default=func.now())

    application = relationship("Application", back_populates="completion_requirements")
