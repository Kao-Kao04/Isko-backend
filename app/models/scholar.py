from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime, ForeignKey, Enum as SAEnum
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import enum
from app.database import Base


class ScholarStatus(str, enum.Enum):
    active = "active"
    probationary = "probationary"
    terminated = "terminated"
    graduated = "graduated"


class Scholar(Base):
    __tablename__ = "scholars"

    id = Column(Integer, primary_key=True, index=True)
    application_id = Column(Integer, ForeignKey("applications.id"), unique=True, nullable=False)
    student_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    scholarship_id = Column(Integer, ForeignKey("scholarships.id"), nullable=False)
    status = Column(SAEnum(ScholarStatus), nullable=False, default=ScholarStatus.active)
    is_graduating = Column(Boolean, default=False)
    expected_graduation = Column(String)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    application  = relationship("Application", back_populates="scholar")
    user         = relationship("User",         foreign_keys=[student_id])
    scholarship  = relationship("Scholarship",  foreign_keys=[scholarship_id])
    semester_records = relationship("SemesterRecord", back_populates="scholar", cascade="all, delete-orphan")


class SemesterRecord(Base):
    __tablename__ = "semester_records"

    id = Column(Integer, primary_key=True, index=True)
    scholar_id = Column(Integer, ForeignKey("scholars.id"), nullable=False)
    semester = Column(String, nullable=False)
    academic_year = Column(String, nullable=False)
    gwa = Column(String)
    is_enrolled = Column(Boolean, default=True)
    notes = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    scholar = relationship("Scholar", back_populates="semester_records")
