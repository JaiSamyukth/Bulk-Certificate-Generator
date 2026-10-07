import os
from pathlib import Path
from typing import Generator

# Override settings for tests BEFORE importing app modules
os.environ["CERTGEN_WORKER_MODE"] = "inline"
os.environ["CERTGEN_DATABASE_URL"] = "sqlite:///test_certgen.db"

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.database import Base
from app.main import app, engine, get_db

@pytest.fixture(autouse=True)
def setup_db() -> Generator[None, None, None]:
    # Ensure fresh DB for each test
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)
    
    # Cleanup file
    if os.path.exists("test_certgen.db"):
        try:
            os.remove("test_certgen.db")
        except:
            pass


@pytest.fixture
def client() -> Generator[TestClient, None, None]:
    with TestClient(app) as c:
        yield c


def test_create_job(client: TestClient) -> None:
    payload = {
        "title": "Test Certificate",
        "course_name": "Test Course",
        "issuer_name": "Test Issuer",
        "recipients": [
            {"recipient_name": "John Doe", "recipient_email": "john@example.com"},
            {"recipient_name": "Jane Doe", "recipient_email": "jane@example.com", "achievement": "Distinction"}
        ]
    }
    
    response = client.post("/api/v1/jobs", json=payload)
    assert response.status_code == 202
    
    data = response.json()
    assert data["status"] == "completed"  # inline worker completes immediately
    assert data["total_recipients"] == 2
    assert "id" in data
    
    job_id = data["id"]
    
    # Check details
    detail_resp = client.get(f"/api/v1/jobs/{job_id}")
    assert detail_resp.status_code == 200
    detail_data = detail_resp.json()
    
    assert detail_data["certificates_successful"] == 2
    assert detail_data["certificates_failed"] == 0
    assert len(detail_data["certificates"]) == 2
    
    cert_id = detail_data["certificates"][0]["id"]
    
    # Download cert
    download_resp = client.get(f"/api/v1/certificates/{cert_id}/download")
    assert download_resp.status_code == 200
    assert download_resp.headers["content-type"] == "application/pdf"


def test_input_validation(client: TestClient) -> None:
    payload = {
        "title": "Test Certificate",
        "course_name": "Test Course",
        "issuer_name": "Test Issuer",
        "recipients": [
            {"recipient_name": "J", "recipient_email": "invalid-email"} # Name too short, invalid email
        ]
    }
    
    response = client.post("/api/v1/jobs", json=payload)
    assert response.status_code == 422
