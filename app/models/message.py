from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, Boolean
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database import Base


class ApplicationMessage(Base):
    __tablename__ = "application_messages"

    id             = Column(Integer, primary_key=True, index=True)
    application_id = Column(Integer, ForeignKey("applications.id"), nullable=False)
    sender_id      = Column(Integer, ForeignKey("users.id"), nullable=False)
    body           = Column(Text, nullable=False)
    is_read        = Column(Boolean, default=False, nullable=False)
    created_at     = Column(DateTime(timezone=True), server_default=func.now())

    application = relationship("Application", back_populates="messages")
    sender      = relationship("User")


class ContactInquiry(Base):
    __tablename__ = "contact_inquiries"

    id         = Column(Integer, primary_key=True, index=True)
    name       = Column(String, nullable=False)
    email      = Column(String, nullable=False)
    subject    = Column(String, nullable=True)
    message    = Column(Text, nullable=False)
    is_read    = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
