import logging
import threading
import time
from queue import Empty, Queue
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import create_db_engine, create_session_factory
from app.generator import build_certificate_pdf, save_certificate_file
from app.models import Certificate, CertificateStatus, Job, JobStatus, utcnow

logger = logging.getLogger(__name__)

# Queue for job IDs to be processed
_job_queue: Queue[str] = Queue()
_workers: list[threading.Thread] = []
_shutdown_event = threading.Event()

def enqueue_job(job_id: str) -> None:
    _job_queue.put(job_id)


def _process_job(job_id: str, session_factory: Any) -> None:
    with session_factory() as session:
        # Fetch the job
        job = session.get(Job, job_id)
        if not job or job.status != JobStatus.PENDING:
            return
            
        # Transition to processing
        job.status = JobStatus.PROCESSING
        job.started_at = utcnow()
        session.commit()
        
        logger.info(f"Started processing job {job_id}")
        
        # Prepare cert info (static for all recipients)
        cert_info = {
            "title": job.title,
            "course_name": job.course_name,
            "issuer_name": job.issuer_name,
            "issue_date": job.issue_date,
            "signatory_name": job.signatory_name,
            "signatory_title": job.signatory_title,
            "description": job.description
        }
        
        try:
            # Batch process certificates to avoid loading all into memory
            # and commit periodically
            batch_size = 100
            
            while True:
                if job.cancel_requested:
                    logger.info(f"Job {job_id} cancellation requested.")
                    break
                    
                # Fetch pending certificates for this job
                certs = session.execute(
                    select(Certificate)
                    .where(
                        Certificate.job_id == job_id,
                        Certificate.status == CertificateStatus.PENDING
                    )
                    .order_by(Certificate.row_number)
                    .limit(batch_size)
                ).scalars().all()
                
                if not certs:
                    break # Done
                    
                for cert in certs:
                    if job.cancel_requested:
                         break
                         
                    recipient = {
                        "recipient_name": cert.recipient_name,
                        "achievement": cert.achievement
                    }
                    
                    try:
                        cert.attempts += 1
                        
                        # Generate PDF
                        pdf_bytes, verification_code = build_certificate_pdf(cert_info, recipient)
                        
                        # Save File
                        file_path = save_certificate_file(job_id, cert.id, pdf_bytes)
                        
                        # Update Cert
                        cert.status = CertificateStatus.SUCCEEDED
                        cert.verification_code = verification_code
                        cert.file_path = file_path
                        cert.file_size = len(pdf_bytes)
                        cert.generated_at = utcnow()
                        
                    except Exception as e:
                        logger.error(f"Failed to generate certificate {cert.id}: {e}", exc_info=True)
                        if cert.attempts >= get_settings().cert_max_attempts:
                            cert.status = CertificateStatus.FAILED
                            cert.errors = [{"field": None, "message": str(e)}]
                            
                # Commit batch
                session.commit()
                # Refresh job state in case cancellation was requested
                session.refresh(job)

        except Exception as e:
            logger.error(f"Job {job_id} encountered a fatal error: {e}", exc_info=True)
            job.error = str(e)
            
        finally:
            # Finalize Job Status
            session.refresh(job)
            
            # Count statuses
            status_counts = dict(
                session.execute(
                    select(Certificate.status, sqlalchemy.func.count())
                    .where(Certificate.job_id == job_id)
                    .group_by(Certificate.status)
                ).all()
            )
            
            pending_count = status_counts.get(CertificateStatus.PENDING, 0)
            failed_count = status_counts.get(CertificateStatus.FAILED, 0)
            invalid_count = status_counts.get(CertificateStatus.INVALID, 0)
            succeeded_count = status_counts.get(CertificateStatus.SUCCEEDED, 0)
            
            if job.cancel_requested:
                job.status = JobStatus.CANCELLED
                # Mark remaining pending as cancelled
                session.execute(
                    sqlalchemy.update(Certificate)
                    .where(
                        Certificate.job_id == job_id,
                        Certificate.status == CertificateStatus.PENDING
                    )
                    .values(status=CertificateStatus.CANCELLED)
                )
            elif job.error:
                job.status = JobStatus.FAILED
            elif failed_count > 0 or invalid_count > 0:
                job.status = JobStatus.COMPLETED_WITH_ERRORS
            else:
                job.status = JobStatus.COMPLETED
                
            job.completed_at = utcnow()
            session.commit()
            logger.info(f"Finished processing job {job_id}. Status: {job.status}")


import sqlalchemy # Ensure available in scope for finalizer

def _worker_loop(session_factory: Any) -> None:
    while not _shutdown_event.is_set():
        try:
            job_id = _job_queue.get(timeout=1.0)
            _process_job(job_id, session_factory)
            _job_queue.task_done()
        except Empty:
            continue
        except Exception as e:
            logger.error(f"Worker thread error: {e}", exc_info=True)


def start_workers(engine: Any) -> None:
    settings = get_settings()
    if settings.worker_mode != "thread":
        return
        
    session_factory = create_session_factory(engine)
    
    _shutdown_event.clear()
    for _ in range(settings.worker_count):
        t = threading.Thread(target=_worker_loop, args=(session_factory,), daemon=True)
        t.start()
        _workers.append(t)
        
    logger.info(f"Started {settings.worker_count} background workers.")


def stop_workers() -> None:
    _shutdown_event.set()
    for t in _workers:
        t.join(timeout=2.0)
    _workers.clear()
    logger.info("Workers stopped.")


def process_inline(job_id: str, session_factory: Any) -> None:
    """For testing or inline worker mode."""
    _process_job(job_id, session_factory)
