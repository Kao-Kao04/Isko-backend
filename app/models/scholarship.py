from sqlalchemy import Column, Integer, String, Text, DateTime, JSON, ForeignKey, Enum as SAEnum, Boolean
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import enum
from app.database import Base


class ScholarshipStatus(str, enum.Enum):
    draft = "draft"
    active = "active"
    closed = "closed"
    archived = "archived"


class CategoryEnum(str, enum.Enum):
    public = "public"
    private = "private"


class Scholarship(Base):
    __tablename__ = "scholarships"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    description = Column(Text)
    slots = Column(Integer)
    deadline = Column(DateTime(timezone=True))
    status = Column(SAEnum(ScholarshipStatus), nullable=False, default=ScholarshipStatus.draft)
    eligible_colleges = Column(JSON)
    eligible_programs = Column(JSON)
    eligible_year_levels = Column(JSON)
    min_gwa = Column(String)
    amount_raw = Column(Integer)
    period = Column(String)
    scholarship_type = Column(String)
    eligibility_text = Column(Text)
    cover_image_url = Column(String)
    category = Column(SAEnum(CategoryEnum, name="categoryenum", create_constraint=True), nullable=True, default=CategoryEnum.public)
    created_by = Column(Integer, ForeignKey("users.id"))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    requirements = relationship("ScholarshipRequirement", back_populates="scholarship", cascade="all, delete-orphan")
    applications = relationship("Application", back_populates="scholarship", cascade="all, delete-orphan")


class ScholarshipRequirement(Base):
    __tablename__ = "scholarship_requirements"

    id = Column(Integer, primary_key=True, index=True)
    scholarship_id = Column(Integer, ForeignKey("scholarships.id"), nullable=False)
    name = Column(String, nullable=False)
    description = Column(Text)
    is_required = Column(Boolean, default=True)

    scholarship = relationship("Scholarship", back_populates="requirements")
