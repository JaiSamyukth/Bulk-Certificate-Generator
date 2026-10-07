import io
import os
import secrets
import string
from io import BytesIO
from pathlib import Path
from typing import Any

from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from reportlab.graphics.barcode import qr
from reportlab.graphics.shapes import Drawing

from app.config import get_settings


def generate_verification_code() -> str:
    # E.g. "A7K9-M2X4" (easy to type, no ambiguous chars like O, 0, I, 1)
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    code = "".join(secrets.choice(alphabet) for _ in range(8))
    return f"{code[:4]}-{code[4:]}"


def build_certificate_pdf(cert_info: dict[str, Any], recipient: dict[str, Any]) -> tuple[bytes, str]:
    """Generates a PDF certificate as a byte string and a verification code.
    
    Returns (pdf_bytes, verification_code).
    """
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=landscape(A4),
        rightMargin=inch,
        leftMargin=inch,
        topMargin=inch,
        bottomMargin=inch,
    )
    
    styles = getSampleStyleSheet()
    
    # Custom Styles
    title_style = ParagraphStyle(
        'TitleStyle',
        parent=styles['Heading1'],
        fontName='Helvetica-Bold',
        fontSize=36,
        alignment=1, # Center
        spaceAfter=30,
        textColor=HexColor('#1f2937')
    )
    
    subtitle_style = ParagraphStyle(
        'SubtitleStyle',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=14,
        alignment=1,
        spaceAfter=20,
        textColor=HexColor('#4b5563')
    )
    
    name_style = ParagraphStyle(
        'NameStyle',
        parent=styles['Heading2'],
        fontName='Helvetica-Bold',
        fontSize=28,
        alignment=1,
        spaceAfter=20,
        textColor=HexColor('#2563eb')
    )
    
    course_style = ParagraphStyle(
        'CourseStyle',
        parent=styles['Heading3'],
        fontName='Helvetica-Bold',
        fontSize=20,
        alignment=1,
        spaceAfter=15,
        textColor=HexColor('#111827')
    )
    
    normal_style = ParagraphStyle(
        'NormalStyle',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=12,
        alignment=1,
        spaceAfter=10
    )

    elements = []

    # Title
    elements.append(Paragraph(cert_info["title"], title_style))
    
    # Statement
    elements.append(Paragraph("This is to certify that", subtitle_style))
    
    # Recipient Name
    elements.append(Paragraph(recipient["recipient_name"], name_style))
    
    # Achievement
    elements.append(Paragraph(f"has achieved {recipient['achievement']} in", subtitle_style))
    
    # Course Name
    elements.append(Paragraph(cert_info["course_name"], course_style))
    
    if cert_info.get("description"):
        elements.append(Spacer(1, 0.2 * inch))
        elements.append(Paragraph(cert_info["description"], normal_style))
    
    elements.append(Spacer(1, 0.5 * inch))

    # Details Table (Signatory and Issue Date)
    issue_date = cert_info["issue_date"].strftime("%B %d, %Y") if hasattr(cert_info["issue_date"], "strftime") else str(cert_info["issue_date"])
    
    signatory = ""
    if cert_info.get("signatory_name"):
        signatory = cert_info["signatory_name"]
        if cert_info.get("signatory_title"):
            signatory += f"<br/><i>{cert_info['signatory_title']}</i>"
            
    issuer = cert_info.get("issuer_name", "")

    # QR Code for verification
    verification_code = generate_verification_code()
    settings = get_settings()
    verify_url = f"{settings.public_base_url}/api/v1/certificates/verify/{verification_code}"
    
    qr_code = qr.QrCodeWidget(verify_url)
    bounds = qr_code.getBounds()
    width = bounds[2] - bounds[0]
    height = bounds[3] - bounds[1]
    qr_drawing = Drawing(100, 100, transform=[100/width,0,0,100/height,0,0])
    qr_drawing.add(qr_code)


    data = [
        [
            Paragraph(f"<b>Issued by:</b> {issuer}<br/><b>Date:</b> {issue_date}", normal_style),
            qr_drawing,
            Paragraph(signatory, normal_style) if signatory else ""
        ]
    ]
    
    table = Table(data, colWidths=[3 * inch, 2 * inch, 3 * inch])
    table.setStyle(TableStyle([
        ('ALIGN', (0, 0), (0, 0), 'LEFT'),
        ('ALIGN', (1, 0), (1, 0), 'CENTER'),
        ('VALIGN', (1, 0), (1, 0), 'MIDDLE'),
        ('ALIGN', (2, 0), (2, 0), 'RIGHT'),
        ('VALIGN', (0, 0), (-1, -1), 'BOTTOM'),
    ]))
    
    elements.append(table)
    
    # Verification text
    elements.append(Spacer(1, 0.2*inch))
    verify_text = Paragraph(f"<font size=8 color='#9ca3af'>Verify at: {verify_url}<br/>Code: {verification_code}</font>", normal_style)
    elements.append(verify_text)

    # Generate PDF
    doc.build(elements)
    
    pdf_bytes = buffer.getvalue()
    buffer.close()
    
    return pdf_bytes, verification_code


def save_certificate_file(job_id: str, cert_id: str, pdf_bytes: bytes) -> str:
    """Saves the PDF and returns the relative file path."""
    settings = get_settings()
    
    job_dir = settings.storage_dir / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    
    file_name = f"{cert_id}.pdf"
    file_path = job_dir / file_name
    
    with open(file_path, "wb") as f:
        f.write(pdf_bytes)
        
    # Return relative path for DB storage (job_id/cert_id.pdf)
    return f"{job_id}/{file_name}"

def get_certificate_file(file_path: str) -> Path | None:
    settings = get_settings()
    full_path = settings.storage_dir / file_path
    if full_path.exists() and full_path.is_file():
        return full_path
    return None
