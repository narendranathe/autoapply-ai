"""
Resume API endpoints.

POST /api/v1/resume/parse    → Upload and parse a resume
POST /api/v1/resume/tailor   → Tailor a resume for a job description
GET  /api/v1/resume/strategies → List available rewrite strategies
"""

import json
import time

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db
from app.models.audit_log import AuditLog
from app.services.llm_service import RewriteStrategy
from app.services.resume_parser import ResumeParser
from app.services.tailoring_pipeline import TailoringPipeline
from app.utils.hashing import hash_jd, hash_pii

router = APIRouter()

# Initialize services
parser = ResumeParser()
pipeline = TailoringPipeline()

# Allowed file types and max size
ALLOWED_EXTENSIONS = {"pdf", "docx", "txt"}
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB


def _get_file_extension(filename: str) -> str:
    """Extract and validate file extension."""
    if "." not in filename:
        raise HTTPException(400, "File must have an extension (.pdf, .docx, .txt)")
    ext = filename.rsplit(".", 1)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(400, f"Unsupported file type: .{ext}. Allowed: {ALLOWED_EXTENSIONS}")
    return ext


@router.post("/parse")
async def parse_resume(
    request: Request,
    file: UploadFile = File(..., description="Resume file (PDF, DOCX, or TXT)"),
    db: AsyncSession = Depends(get_db),
):
    """
    Parse a resume into structured data.

    Returns the number of bullets, detected skills, companies,
    dates, and section breakdown. Does NOT call any LLM.
    Useful for previewing what the parser found before tailoring.
    """
    start_time = time.perf_counter()
    request_id = getattr(request.state, "request_id", "unknown")

    # Validate file
    ext = _get_file_extension(file.filename or "unknown.txt")
    content = await file.read()

    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(413, f"File too large. Maximum: {MAX_FILE_SIZE // (1024*1024)}MB")

    if len(content) == 0:
        raise HTTPException(400, "File is empty")

    # Parse
    if ext == "docx":
        ast = parser.parse_docx(content)
    elif ext == "pdf":
        ast = parser.parse_pdf(content)
    else:
        ast = parser.parse_text(content.decode("utf-8", errors="replace"))

    duration_ms = int((time.perf_counter() - start_time) * 1000)

    # Audit log
    log = AuditLog(
        user_hash=hash_pii(request.headers.get("X-User-ID", "anonymous")),
        request_id=request_id,
        action="resume.parse",
        metadata_json=json.dumps(
            {
                "format": ext,
                "file_size_bytes": len(content),
                "bullet_count": ast.bullet_count,
                "skill_count": len(ast.skills),
            }
        ),
        success=True,
        duration_ms=duration_ms,
    )
    db.add(log)

    return {
        "bullet_count": ast.bullet_count,
        "skills_detected": sorted(ast.skills),
        "companies_found": sorted(ast.companies),
        "roles_found": sorted(ast.roles),
        "dates_found": sorted(ast.dates),
        "sections": ast.sections,
        "warnings": ast.parse_warnings,
        "duration_ms": duration_ms,
    }


@router.post("/tailor")
async def tailor_resume_endpoint(
    request: Request,
    file: UploadFile = File(..., description="Resume file (PDF, DOCX, or TXT)"),
    job_description: str = Form(..., min_length=50, max_length=10000),
    company_name: str = Form(..., min_length=1, max_length=255),
    role_title: str = Form(..., min_length=1, max_length=255),
    strategy: str = Form(default="moderate"),
    provider: str = Form(default="fallback"),
    db: AsyncSession = Depends(get_db),
):
    """
    Tailor a resume for a specific job description.

    Flow:
    1. Parse resume into structured AST
    2. Call LLM to rewrite bullets (or use keyword fallback)
    3. Validate rewrite against original (anti-hallucination)
    4. Return result with validation details

    The response includes whether the rewrite was accepted or rejected.
    If rejected, the original bullets are returned with an explanation.
    """
    start_time = time.perf_counter()
    request_id = getattr(request.state, "request_id", "unknown")

    # Validate inputs
    ext = _get_file_extension(file.filename or "unknown.txt")
    content = await file.read()

    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(413, f"File too large. Maximum: {MAX_FILE_SIZE // (1024*1024)}MB")

    try:
        rewrite_strategy = RewriteStrategy(strategy)
    except ValueError as exc:
        raise HTTPException(
            400, f"Invalid strategy: {strategy}. Use: slight_tweak, moderate, ground_up"
        ) from exc

    encrypted_api_key = ""

    # Run the pipeline
    result = await pipeline.run(
        resume_bytes=content,
        file_format=ext,
        job_description=job_description,
        strategy=rewrite_strategy,
        provider=provider,
        encrypted_api_key=encrypted_api_key,
    )

    duration_ms = int((time.perf_counter() - start_time) * 1000)

    # Audit log
    log = AuditLog(
        user_hash=hash_pii(request.headers.get("X-User-ID", "anonymous")),
        request_id=request_id,
        action="resume.tailor",
        metadata_json=json.dumps(
            {
                "company": company_name,
                "role": role_title,
                "strategy": strategy,
                "provider": provider,
                "jd_hash": hash_jd(job_description),
                "rewrite_accepted": result.rewrite_accepted,
                "used_fallback": result.used_fallback,
                "bullet_count": len(result.bullets),
            }
        ),
        success=result.rewrite_accepted,
        duration_ms=duration_ms,
    )
    db.add(log)

    return {
        "bullets": result.bullets,
        "rewrite_accepted": result.rewrite_accepted,
        "used_fallback": result.used_fallback,
        "summary": result.summary,
        "validation": result.validation.to_dict() if result.validation else None,
        "resume_metadata": result.resume_ast.to_dict(),
        "performance": {
            "total_ms": result.total_duration_ms,
            "parse_ms": result.parse_duration_ms,
            "llm_ms": result.llm_duration_ms,
            "validation_ms": result.validation_duration_ms,
        },
    }


@router.get("/strategies")
async def list_strategies():
    """List available rewrite strategies with descriptions."""
    return {
        "strategies": [
            {
                "id": "slight_tweak",
                "name": "Slight Tweak",
                "description": "Minimal changes. Swap 1-3 keywords to match JD terminology.",
                "use_when": "Applying to a very similar role as a previous application.",
            },
            {
                "id": "moderate",
                "name": "Moderate Rewrite",
                "description": "Restructure sentences, lead with JD-relevant action verbs.",
                "use_when": "Applying to a related but different role.",
            },
            {
                "id": "ground_up",
                "name": "Ground-Up Rephrase",
                "description": "Significantly rephrase while keeping all facts true.",
                "use_when": "Applying to a new domain or significantly different role.",
            },
        ]
    }
