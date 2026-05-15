from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, Enum as SAEnum
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import enum
from app.database import Base


class UserRole(str, enum.Enum):
    student = "student"
    osfa_staff = "osfa_staff"
    super_admin = "super_admin"


class AccountStatus(str, enum.Enum):
    unregistered = "unregistered"          # email verified, no docs submitted yet
    pending_verification = "pending_verification"  # docs submitted, awaiting OSFA review
    verified = "verified"                  # OSFA approved
    rejected = "rejected"                  # OSFA rejected
    approved = "approved"                  # reserved for OSFA staff accounts


class DepartmentEnum(str, enum.Enum):
    public = "public"
    private = "private"


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, nullable=False, index=True)
    hashed_password = Column(String, nullable=False)
    role = Column(SAEnum(UserRole), nullable=False, default=UserRole.student)
    is_active = Column(Boolean, default=True)
    is_verified = Column(Boolean, default=False)
    account_status = Column(SAEnum(AccountStatus), nullable=False, default=AccountStatus.unregistered)
    rejection_remarks = Column(String, nullable=True)
    department = Column(SAEnum(DepartmentEnum, name="departmentenum", create_constraint=True), nullable=True, default=None)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    student_profile = relationship("StudentProfile", back_populates="user", uselist=False)
    applications = relationship("Application", back_populates="student", foreign_keys="Application.student_id")
    notifications = relationship("Notification", back_populates="user")
    registration_documents = relationship("RegistrationDocument", back_populates="user", cascade="all, delete-orphan")


class StudentProfile(Base):
    __tablename__ = "student_profiles"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), unique=True, nullable=False)
    student_number = Column(String, unique=True, nullable=False)
    first_name = Column(String, nullable=False)
    last_name = Column(String, nullable=False)
    middle_name = Column(String)
    college = Column(String, nullable=False)
    program = Column(String, nullable=False)
    year_level = Column(Integer, nullable=False)
    gwa = Column(String)

    # Address
    street_barangay   = Column(String, nullable=True)
    city_municipality = Column(String, nullable=True)
    province          = Column(String, nullable=True)
    zip_code          = Column(String, nullable=True)

    # Parents
    father_name       = Column(String, nullable=True)
    father_occupation = Column(String, nullable=True)
    mother_name       = Column(String, nullable=True)
    mother_occupation = Column(String, nullable=True)

    # Family income
    income_source     = Column(String, nullable=True)
    monthly_income    = Column(String, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    user = relationship("User", back_populates="student_profile")
