"""
ORM models for the persistence layer.
Covers user accounts, bulk CSV jobs, and per-email verification logs.
"""

from __future__ import annotations

import datetime
from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, ForeignKey, Text
from sqlalchemy.orm import relationship
from app.services.database import Base

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), unique=True, index=True, nullable=False)
    api_key = Column(String(255), unique=True, index=True, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    
    # TODO: wire this up once the billing page lands
    monthly_quota = Column(Integer, default=1000)
    used_quota = Column(Integer, default=0)

    jobs = relationship("BulkJob", back_populates="user")


class BulkJob(Base):
    __tablename__ = "bulk_jobs"

    id = Column(String(36), primary_key=True, index=True)  # UUIDs as strings — SQLite has no native UUID
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    
    status = Column(String(50), default="PENDING", index=True) # PENDING → PROCESSING → COMPLETED | FAILED
    
    file_path = Column(String(500), nullable=False) # raw upload — deleted after processing for privacy
    output_file_path = Column(String(500), nullable=True) # result CSV the user downloads
    
    total_rows = Column(Integer, default=0)
    processed_rows = Column(Integer, default=0)
    
    # Denormalised tallies so the status endpoint doesn't need to aggregate logs
    valid_count = Column(Integer, default=0)
    invalid_count = Column(Integer, default=0)
    suspicious_count = Column(Integer, default=0)
    uncertain_count = Column(Integer, default=0)
    
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)
    error_message = Column(Text, nullable=True)

    user = relationship("User", back_populates="jobs")
    logs = relationship("VerificationLog", back_populates="job")


class VerificationLog(Base):
    """One row per email verified. Powers the analytics dashboard."""
    __tablename__ = "verification_logs"

    id = Column(Integer, primary_key=True, index=True)
    job_id = Column(String(36), ForeignKey("bulk_jobs.id"), nullable=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    
    email_hash = Column(String(64), index=True, nullable=False) # SHA-256 prefix — no PII in the DB
    
    status = Column(String(50), nullable=False) # mirrors VerificationStatus enum
    confidence = Column(Float, nullable=False)
    failed_layer = Column(String(50), nullable=True)
    
    # These two columns let us prove the ML layer's contribution in the dissertation
    ml_score = Column(Float, nullable=True)
    smtp_attempted = Column(Boolean, default=False)
    ml_short_circuited = Column(Boolean, default=False)
    
    # Latency tracking
    total_latency_ms = Column(Float, nullable=False)
    timestamp = Column(DateTime, default=datetime.datetime.utcnow, index=True)

    job = relationship("BulkJob", back_populates="logs")
