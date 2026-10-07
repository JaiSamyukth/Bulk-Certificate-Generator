from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request, Response, status
from fastapi.responses import FileResponse
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import models, schemas
from app.config import get_settings
from app.database import create_db_engine, create_session_factory
from app.generator import get_certificate_file
from app.worker import enqueue_job, process_inline, start_workers, stop_workers

settings = get_settings()
engine = create_db_engine(settings.database_url)
SessionFactory = create_session_factory(engine)

def get_db() -> AsyncGenerator[Session, None]:
    with SessionFactory() as session:
        yield session


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    # Ensure DB schema exists
    models.Base.metadata.create_all(bind=engine)
    
    # Start workers
    start_workers(engine)
    
    # Resume any pending jobs from a previous run
    with SessionFactory() as session:
        pending_jobs = session.execute(
            select(models.Job.id).where(models.Job.status == models.JobStatus.PENDING)
        ).scalars().all()
        
        # Reset processing jobs back to pending since they were interrupted
        interrupted_jobs = session.execute(
            select(models.Job.id).where(models.Job.status == models.JobStatus.PROCESSING)
        ).scalars().all()
        
        if interrupted_jobs:
            session.execute(
                sqlalchemy.update(models.Job)
                .where(models.Job.id.in_(interrupted_jobs))
                .values(status=models.JobStatus.PENDING, started_at=None)
            )
            session.commit()
            pending_jobs.extend(interrupted_jobs)
            
        for job_id in pending_jobs:
            enqueue_job(job_id)
            
    yield
    
    # Shutdown workers
    stop_workers()


app = FastAPI(
    title=settings.app_name,
    version="1.0.0",
    lifespan=lifespan,
    description="API for bulk generating PDF certificates.",
)

import sqlalchemy # Needed in lifespan


@app.post("/api/v1/jobs", response_model=schemas.JobSummaryResponse, status_code=status.HTTP_202_ACCEPTED)
def create_job(job_in: schemas.JobCreate, db: Session = Depends(get_db)) -> Any:
    """Submit a new bulk certificate generation job."""
    
    if job_in.idempotency_key:
        existing = db.execute(
            select(models.Job).where(models.Job.idempotency_key == job_in.idempotency_key)
        ).scalar_one_or_none()
        if existing:
            return existing

    job = models.Job(
        title=job_in.title,
        course_name=job_in.course_name,
        issuer_name=job_in.issuer_name,
        issue_date=job_in.issue_date,
        signatory_name=job_in.signatory_name,
        signatory_title=job_in.signatory_title,
        description=job_in.description,
        idempotency_key=job_in.idempotency_key,
        total_recipients=len(job_in.recipients),
    )
    db.add(job)
    db.flush() # get job.id

    certificates = []
    for i, rec_in in enumerate(job_in.recipients, start=1):
        cert = models.Certificate(
            job_id=job.id,
            row_number=i,
            recipient_name=rec_in.recipient_name,
            recipient_email=rec_in.recipient_email,
            achievement=rec_in.achievement,
            status=models.CertificateStatus.PENDING,
        )
        certificates.append(cert)
        
    db.add_all(certificates)
    db.commit()
    db.refresh(job)

    if settings.worker_mode == "inline":
        process_inline(job.id, SessionFactory)
        db.refresh(job)
    else:
        enqueue_job(job.id)

    return job


@app.get("/api/v1/jobs/{job_id}", response_model=schemas.JobDetailResponse)
def get_job(job_id: str, db: Session = Depends(get_db)) -> Any:
    """Get the status and details of a specific job, including all its certificates."""
    job = db.get(models.Job, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
        
    status_counts = dict(
        db.execute(
            select(models.Certificate.status, func.count())
            .where(models.Certificate.job_id == job_id)
            .group_by(models.Certificate.status)
        ).all()
    )
    
    succeeded = status_counts.get(models.CertificateStatus.SUCCEEDED, 0)
    failed = status_counts.get(models.CertificateStatus.FAILED, 0)
    invalid = status_counts.get(models.CertificateStatus.INVALID, 0)
    
    # Create the response manually because we need to inject the aggregated counts
    return schemas.JobDetailResponse(
        id=job.id,
        status=job.status.value,
        course_name=job.course_name,
        total_recipients=job.total_recipients,
        created_at=job.created_at,
        started_at=job.started_at,
        completed_at=job.completed_at,
        error=job.error,
        certificates_processed=sum(status_counts.values()) - status_counts.get(models.CertificateStatus.PENDING, 0),
        certificates_successful=succeeded,
        certificates_failed=failed + invalid,
        certificates=[
            schemas.CertificateResponse.model_validate(c)
            for c in job.certificates
        ]
    )

@app.get("/api/v1/jobs")
def list_jobs(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)) -> list[schemas.JobSummaryResponse]:
    """List recent jobs."""
    jobs = db.execute(
        select(models.Job).order_by(models.Job.created_at.desc()).offset(skip).limit(limit)
    ).scalars().all()
    return [schemas.JobSummaryResponse.model_validate(job) for job in jobs]


@app.get("/api/v1/certificates/{cert_id}/download")
def download_certificate(cert_id: str, db: Session = Depends(get_db)) -> Any:
    """Download a generated certificate PDF."""
    cert = db.get(models.Certificate, cert_id)
    if not cert:
        raise HTTPException(status_code=404, detail="Certificate not found")
        
    if cert.status != models.CertificateStatus.SUCCEEDED or not cert.file_path:
        raise HTTPException(status_code=400, detail=f"Certificate not ready. Current status: {cert.status.value}")
        
    file_path = get_certificate_file(cert.file_path)
    if not file_path:
        raise HTTPException(status_code=404, detail="Certificate file not found on disk")
        
    filename = f"certificate_{cert.recipient_name.replace(' ', '_')}.pdf" if cert.recipient_name else "certificate.pdf"
    
    return FileResponse(
        path=file_path,
        filename=filename,
        media_type="application/pdf"
    )
    

@app.get("/api/v1/certificates/verify/{code}")
def verify_certificate(code: str, db: Session = Depends(get_db)) -> Any:
    """Verify a certificate by its unique code (used in QR codes)."""
    cert = db.execute(
        select(models.Certificate).where(models.Certificate.verification_code == code)
    ).scalar_one_or_none()
    
    if not cert or cert.status != models.CertificateStatus.SUCCEEDED:
        raise HTTPException(status_code=404, detail="Invalid verification code")
        
    job = db.get(models.Job, cert.job_id)
    
    return {
        "valid": True,
        "recipient_name": cert.recipient_name,
        "achievement": cert.achievement,
        "course_name": job.course_name,
        "issuer_name": job.issuer_name,
        "issue_date": job.issue_date,
        "issued_at": cert.generated_at
    }
