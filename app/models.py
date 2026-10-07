"""ORM models.

A ``Job`` is one bulk generation request. Every submitted recipient becomes one
``Certificate`` row - including invalid ones - so the client can always see the
outcome of every row it sent.
"""

from __future__ import annotations

import enum
import uuid
from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import JSON, Boolean, Date, DateTime, Enum, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_id() -> str:
    return str(uuid.uuid4())


class JobStatus(str, enum.Enum):
    PENDING = "pending"  # queued, not picked up by a worker yet
    PROCESSING = "processing"  # a worker is generating certificates
    COMPLETED = "completed"  # every recipient got a certificate
    COMPLETED_WITH_ERRORS = "completed_with_errors"  # some succeeded, some failed/invalid
    FAILED = "failed"  # no certificate could be generated
    CANCELLED = "cancelled"  # cancelled by the client before finishing


class CertificateStatus(str, enum.Enum):
    PENDING = "pending"  # valid, waiting to be generated
    SUCCEEDED = "succeeded"  # PDF generated and stored
    FAILED = "failed"  # valid input, but generation failed
    INVALID = "invalid"  # rejected by validation, never generated
    CANCELLED = "cancelled"  # skipped because the job was cancelled


ACTIVE_JOB_STATUSES = frozenset({JobStatus.PENDING, JobStatus.PROCESSING})
TERMINAL_JOB_STATUSES = frozenset(set(JobStatus) - ACTIVE_JOB_STATUSES)


def _enum_column(enum_cls: type[enum.Enum]) -> Enum:
    # Stored as VARCHAR (not a native DB enum) so adding a status never needs a
    # database-specific migration.
    return Enum(
        enum_cls,
        native_enum=False,
        length=32,
        values_callable=lambda members: [m.value for m in members],
        validate_strings=True,
    )


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    status: Mapped[JobStatus] = mapped_column(_enum_column(JobStatus), default=JobStatus.PENDING, index=True)
    source: Mapped[str] = mapped_column(String(16), default="json")

    # Shared certificate information (the same for every recipient in the job)
    title: Mapped[str] = mapped_column(String(120))
    course_name: Mapped[str] = mapped_column(String(200))
    issuer_name: Mapped[str] = mapped_column(String(200))
    issue_date: Mapped[date] = mapped_column(Date)
    signatory_name: Mapped[str | None] = mapped_column(String(120))
    signatory_title: Mapped[str | None] = mapped_column(String(120))
    description: Mapped[str | None] = mapped_column(Text)

    total_recipients: Mapped[int] = mapped_column(Integer, default=0)
    idempotency_key: Mapped[str | None] = mapped_column(String(128), unique=True)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    error: Mapped[str | None] = mapped_column(Text)  # job-level (infrastructure) failure

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    certificates: Mapped[list[Certificate]] = relationship(
        back_populates="job", cascade="all, delete-orphan", passive_deletes=True
    )


class Certificate(Base):
    __tablename__ = "certificates"
    __table_args__ = (
        Index("ix_certificates_job_status", "job_id", "status"),
        Index("ix_certificates_job_row", "job_id", "row_number"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"))
    row_number: Mapped[int] = mapped_column(Integer)  # 1-based position in the submitted list
    status: Mapped[CertificateStatus] = mapped_column(
        _enum_column(CertificateStatus), default=CertificateStatus.PENDING
    )

    recipient_name: Mapped[str | None] = mapped_column(String(200))
    recipient_email: Mapped[str | None] = mapped_column(String(320))
    achievement: Mapped[str | None] = mapped_column(String(200))

    # Original submitted data - only kept for invalid rows, to help debugging.
    raw_data: Mapped[Any] = mapped_column(JSON(none_as_null=True), nullable=True)
    # List of {"field": str | None, "message": str}
    errors: Mapped[Any] = mapped_column(JSON(none_as_null=True), nullable=True)

    verification_code: Mapped[str | None] = mapped_column(String(16), unique=True)
    file_path: Mapped[str | None] = mapped_column(String(500))  # storage key, relative
    file_size: Mapped[int | None] = mapped_column(Integer)
    attempts: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    generated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    job: Mapped[Job] = relationship(back_populates="certificates")
