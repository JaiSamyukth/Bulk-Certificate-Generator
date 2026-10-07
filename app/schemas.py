from datetime import date, datetime
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator


class RecipientInput(BaseModel):
    recipient_name: str = Field(..., min_length=2, max_length=200)
    recipient_email: EmailStr
    achievement: str = Field(default="Successful Completion", max_length=200)

    @field_validator("recipient_name", "achievement")
    @classmethod
    def strip_whitespace(cls, v: str) -> str:
        return v.strip()


class JobCreate(BaseModel):
    title: str = Field(default="Certificate of Achievement", min_length=5, max_length=120)
    course_name: str = Field(..., min_length=3, max_length=200)
    issuer_name: str = Field(..., min_length=3, max_length=200)
    issue_date: date = Field(default_factory=date.today)
    signatory_name: str | None = Field(default=None, max_length=120)
    signatory_title: str | None = Field(default=None, max_length=120)
    description: str | None = Field(default=None)

    idempotency_key: str | None = Field(default=None, max_length=128)
    recipients: list[RecipientInput] = Field(..., min_length=1)

    @model_validator(mode="after")
    def validate_recipients_size(self) -> Self:
        from app.config import get_settings
        max_recipients = get_settings().max_recipients_per_job
        if len(self.recipients) > max_recipients:
            raise ValueError(f"Too many recipients. Maximum is {max_recipients}")
        return self


class ErrorDetail(BaseModel):
    field: str | None
    message: str


class CertificateResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    row_number: int
    status: str

    recipient_name: str | None = None
    recipient_email: str | None = None
    achievement: str | None = None
    verification_code: str | None = None

    errors: list[ErrorDetail] | None = None


class JobSummaryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    status: str
    course_name: str
    total_recipients: int
    
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error: str | None = None


class JobStatusResponse(JobSummaryResponse):
    certificates_processed: int
    certificates_successful: int
    certificates_failed: int


class JobDetailResponse(JobStatusResponse):
    certificates: list[CertificateResponse]
