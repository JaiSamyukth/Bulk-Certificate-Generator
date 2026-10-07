# Bulk Certificate Generator

A highly robust, multi-threaded FastAPI backend designed for generating PDF certificates in bulk. It receives a list of recipients, validates the input, processes the certificate generation asynchronously using background workers, tracks the exact status of each certificate, and allows clients to download the final PDFs.

## Features
- **FastAPI** for high-performance API endpoints and automated OpenAPI documentation.
- **SQLAlchemy (SQLite default, Postgres ready)** for robust tracking of job statuses and individual recipient states.
- **Background Processing** using a thread pool. The system handles large batches without blocking the main event loop, saving memory by streaming and committing in small batches.
- **ReportLab** for dynamically generating A4 landscape PDFs with embedded QR codes for verification.
- **Pydantic** for rigorous validation of input payloads.
- **Resilient**: If a generation step fails for one recipient, it doesn't block the rest. It retries failures and accurately reports `completed_with_errors` if needed.

## Setup

1. Make sure you have Python 3.12+ installed.
2. Clone the repository and navigate to the project directory.
3. Create and activate a virtual environment:
   ```bash
   python -m venv venv
   source venv/Scripts/activate  # Windows
   ```
4. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

## Running the Application

Start the FastAPI server using Uvicorn:
```bash
uvicorn app.main:app --reload
```
By default, the server runs on `http://localhost:8000`. 
- Interactive API Documentation: `http://localhost:8000/docs`
- Generated PDFs are stored in the `data/certificates/` directory.
- The SQLite database is created automatically at `data/certgen.db`.

## Running Tests

Run the test suite using pytest:
```bash
pytest
```

## API Usage Example

### 1. Submit a Job
Send a POST request to `/api/v1/jobs` with the certificate details and a list of recipients.

```bash
curl -X 'POST' \
  'http://localhost:8000/api/v1/jobs' \
  -H 'accept: application/json' \
  -H 'Content-Type: application/json' \
  -d '{
  "title": "Certificate of Completion",
  "course_name": "Advanced Python Architecture",
  "issuer_name": "ACME Tech",
  "signatory_name": "Jane Doe",
  "signatory_title": "Lead Instructor",
  "recipients": [
    {
      "recipient_name": "Alice Smith",
      "recipient_email": "alice@example.com",
      "achievement": "Excellent Performance"
    },
    {
      "recipient_name": "Bob Jones",
      "recipient_email": "bob@example.com"
    }
  ]
}'
```
Returns a `Job ID` (e.g. `d3b07384-d113-43...`) and status (e.g. `pending`).

### 2. Check Job Status
Send a GET request to `/api/v1/jobs/{job_id}` to see the progress and individual certificate IDs.

```bash
curl -X 'GET' 'http://localhost:8000/api/v1/jobs/{job_id}' -H 'accept: application/json'
```

### 3. Download a Certificate
Once a certificate's status is `succeeded`, use its `id` from the job detail response to download the PDF:

```bash
curl -X 'GET' 'http://localhost:8000/api/v1/certificates/{cert_id}/download' --output certificate.pdf
```

## Design Decisions
- **Background Worker Threads:** Chosen over Celery for simplicity and zero external dependencies (no Redis/RabbitMQ required). FastAPI's lifespan events seamlessly manage the worker lifecycle, utilizing a thread-safe Queue and SQLAlchemy `check_same_thread=False` with WAL enabled. 
- **Database Model Structure:** Instead of storing just a JSON blob of failures, the system models every single recipient as a unique row in the database. This guarantees high traceability, making it trivial to build granular progress bars on the frontend and debug exact validation failures per row.
- **ReportLab over HTML-to-PDF:** ReportLab is extremely fast, uses minimal memory, and doesn't require a headless browser (like Playwright/wkhtmltopdf) to be installed on the host machine.
