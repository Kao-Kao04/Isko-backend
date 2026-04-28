from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, JSON, Enum as SAEnum
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import enum
from app.database import Base


class ApplicationStatus(str, enum.Enum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"
    incomplete = "incomplete"
    withdrawn = "withdrawn"


class EvalStatus(str, enum.Enum):
    not_started = "not_started"
    in_review = "in_review"
    completed = "completed"


class Application(Base):
    __tablename__ = "applications"

    id = Column(Integer, primary_key=True, index=True)
    student_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    scholarship_id = Column(Integer, ForeignKey("scholarships.id"), nullable=False)
    status = Column(SAEnum(ApplicationStatus), nullable=False, default=ApplicationStatus.pending)
    eval_status = Column(SAEnum(EvalStatus), nullable=False, default=EvalStatus.not_started)
    rejected_docs = Column(JSON, default=list)
    eval_score = Column(JSON, nullable=True)
    remarks = Column(Text)
    submitted_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    student = relationship("User", back_populates="applications", foreign_keys=[student_id])
    scholarship = relationship("Scholarship", back_populates="applications")
    documents = relationship("ApplicationDocument", back_populates="application", cascade="all, delete-orphan")
    audit_entries = relationship("AuditEntry", back_populates="application", cascade="all, delete-orphan")
    appeal = relationship("Appeal", back_populates="application", uselist=False, cascade="all, delete-orphan")
    scholar = relationship("Scholar", back_populates="application", uselist=False, cascade="all, delete-orphan")
