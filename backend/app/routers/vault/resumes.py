"""
Vault sub-module: resume upload, list, get, delete, update, download, sync-markdown.
"""

import hashlib
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import Response
from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user, get_db
from app.models.resume import Resume
from app.models.user import User
from app.services.embedding_service import build_tfidf_vector

from ._shared import _resume_parser

router = APIRouter()


# ── Upload ─────────────────────────────────────────────────────────────────


@router.post("/upload", status_code=status.HTTP_201_CREATED)
async def upload_resume(
    file: UploadFile = File(...),
    version_tag: str | None = Form(None),
    target_company: str | None = Form(None),
    target_role: str | None = Form(None),
    is_base_template: bool = Form(False),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    Upload a resume file (PDF, DOCX, or .tex) to the vault.

    Parses content, builds TF-IDF vector, stores in DB.
    Personal data stored here is for retrieval/ATS only — canonical source
    is the user's private GitHub vault.
    """

    file_bytes = await file.read()
    filename = file.filename or "resume"
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "unknown"

    if ext not in {"pdf", "docx", "tex", "txt"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported file type: {ext}. Supported: pdf, docx, tex, txt",
        )

    # Dedup check: skip re-uploading a file already in the vault (by SHA-256)
    file_hash = hashlib.sha256(file_bytes).hexdigest()
    existing = (
        await db.execute(
            select(Resume).where(Resume.user_id == user.id, Resume.file_hash == file_hash)
        )
    ).scalar_one_or_none()
    if existing:
        logger.info(
            f"Skipping duplicate upload {filename} (hash={file_hash[:12]}…) for user {user.id}"
        )
        return {
            "status": "already_synced",
            "file_hash": file_hash,
            "resume_id": str(existing.id),
            "filename": filename,
        }

    # Parse content
    raw_text = ""
    latex_content = None
    parse_result = None

    try:
        if ext == "pdf":
            parse_result = _resume_parser.parse_pdf(file_bytes)
        elif ext == "docx":
            parse_result = _resume_parser.parse_docx(file_bytes)
        elif ext == "tex":
            raw_text = file_bytes.decode("utf-8", errors="replace")
            latex_content = raw_text
        else:
            raw_text = file_bytes.decode("utf-8", errors="replace")

        if parse_result:
            raw_text = " ".join(b.text for b in parse_result.bullets)
    except Exception as e:
        logger.warning(f"Parse error for {filename}: {e}")
        raw_text = file_bytes.decode("utf-8", errors="replace")

    # Build TF-IDF vector
    tfidf_vec = build_tfidf_vector(raw_text) if raw_text else {}

    # Extract structured data from parse result
    skills = list(parse_result.skills) if parse_result else []
    companies = list(parse_result.companies) if parse_result else []
    bullet_count = len(parse_result.bullets) if parse_result else 0

    # Compute ATS score if we have a target company/role context
    ats_score_val = None

    # Build resume row
    resume = Resume(
        user_id=user.id,
        filename=filename,
        file_type=ext,
        file_hash=file_hash,
        raw_text=raw_text[:50000],  # cap at 50K chars
        latex_content=latex_content,
        bullet_count=bullet_count,
        skills_detected=skills,
        companies_found=companies,
        tfidf_vector=tfidf_vec,
        version_tag=version_tag,
        recruiter_filename=f"{user.email_hash[:8]}.pdf",  # placeholder; overridden on generate
        is_base_template=is_base_template,
        is_generated=False,
        target_company=target_company,
        target_role=target_role,
        ats_score=ats_score_val,
    )

    db.add(resume)
    await db.commit()
    await db.refresh(resume)

    logger.info(f"Uploaded resume {filename} for user {user.id} (id={resume.id})")

    return {
        "resume_id": str(resume.id),
        "filename": filename,
        "file_type": ext,
        "bullet_count": bullet_count,
        "skills_detected": skills[:10],
        "version_tag": version_tag,
        "parse_warnings": parse_result.parse_warnings if parse_result else [],
    }


# ── Batch Upload ────────────────────────────────────────────────────────────


@router.post("/resumes/batch-upload")
async def batch_upload_resumes(
    files: list[UploadFile] = File(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """
    Upload multiple resumes in a single request.

    Skips files already present in the vault (by SHA-256 hash).
    Returns per-file status: uploaded | already_synced | error | unsupported_type
    """
    results: list[dict] = []

    for f in files:
        fname = f.filename or "resume"
        try:
            file_bytes = await f.read()
            fhash = hashlib.sha256(file_bytes).hexdigest()
            ext = fname.rsplit(".", 1)[-1].lower() if "." in fname else "unknown"

            if ext not in {"pdf", "docx", "tex", "txt"}:
                results.append({"filename": fname, "status": "unsupported_type", "ext": ext})
                continue

            # Dedup: skip files already in vault
            dup = (
                await db.execute(
                    select(Resume).where(Resume.user_id == user.id, Resume.file_hash == fhash)
                )
            ).scalar_one_or_none()
            if dup:
                results.append({"filename": fname, "status": "already_synced", "file_hash": fhash})
                continue

            # Parse content
            raw_text = ""
            latex_content = None
            parse_result = None

            try:
                if ext == "pdf":
                    parse_result = _resume_parser.parse_pdf(file_bytes)
                elif ext == "docx":
                    parse_result = _resume_parser.parse_docx(file_bytes)
                elif ext == "tex":
                    raw_text = file_bytes.decode("utf-8", errors="replace")
                    latex_content = raw_text
                else:
                    raw_text = file_bytes.decode("utf-8", errors="replace")

                if parse_result:
                    raw_text = " ".join(b.text for b in parse_result.bullets)
            except Exception as parse_err:
                logger.warning(f"[batch-upload] Parse error for {fname}: {parse_err}")
                raw_text = file_bytes.decode("utf-8", errors="replace")

            tfidf_vec = build_tfidf_vector(raw_text) if raw_text else {}
            skills = list(parse_result.skills) if parse_result else []
            companies = list(parse_result.companies) if parse_result else []
            bullet_count = len(parse_result.bullets) if parse_result else 0

            resume = Resume(
                user_id=user.id,
                filename=fname,
                file_type=ext,
                file_hash=fhash,
                raw_text=raw_text[:50000],
                latex_content=latex_content,
                bullet_count=bullet_count,
                skills_detected=skills,
                companies_found=companies,
                tfidf_vector=tfidf_vec,
                recruiter_filename=f"{user.email_hash[:8]}.pdf",
                is_base_template=False,
                is_generated=False,
            )
            db.add(resume)
            await db.flush()  # get resume.id without committing yet

            results.append(
                {
                    "filename": fname,
                    "status": "uploaded",
                    "file_hash": fhash,
                    "resume_id": str(resume.id),
                    "bullet_count": bullet_count,
                }
            )

        except Exception as e:
            logger.warning(f"[batch-upload] Unexpected error for {fname}: {e}")
            results.append({"filename": fname, "status": "error", "error": str(e)})

    await db.commit()

    uploaded = sum(1 for r in results if r["status"] == "uploaded")
    already_synced = sum(1 for r in results if r["status"] == "already_synced")
    logger.info(
        f"[batch-upload] user={user.id} total={len(results)} "
        f"uploaded={uploaded} already_synced={already_synced}"
    )

    return {
        "results": results,
        "total": len(results),
        "uploaded": uploaded,
        "already_synced": already_synced,
    }


# ── List ───────────────────────────────────────────────────────────────────


@router.get("/resumes")
async def list_resumes(
    page: int = 1,
    per_page: int = 20,
    company: str | None = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """List all resumes in the user's vault, newest first."""

    stmt = select(Resume).where(Resume.user_id == user.id)
    if company:
        stmt = stmt.where(Resume.target_company.ilike(f"%{company}%"))
    stmt = stmt.order_by(Resume.created_at.desc()).offset((page - 1) * per_page).limit(per_page)

    result = await db.execute(stmt)
    resumes = result.scalars().all()

    return {
        "items": [
            {
                "resume_id": str(r.id),
                "filename": r.filename,
                "version_tag": r.version_tag,
                "target_company": r.target_company,
                "target_role": r.target_role,
                "ats_score": r.ats_score,
                "bullet_count": r.bullet_count,
                "is_base_template": r.is_base_template,
                "is_generated": r.is_generated,
                "github_path": r.github_path,
                "created_at": r.created_at.isoformat(),
            }
            for r in resumes
        ],
        "page": page,
        "per_page": per_page,
    }


# ── Get single resume ──────────────────────────────────────────────────────


@router.get("/resumes/{resume_id}")
async def get_resume(
    resume_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """Get a single resume including its full text/latex content."""
    result = await db.execute(
        select(Resume).where(Resume.id == resume_id, Resume.user_id == user.id)
    )
    r = result.scalar_one_or_none()
    if not r:
        raise HTTPException(status_code=404, detail="Resume not found")

    return {
        "resume_id": str(r.id),
        "filename": r.filename,
        "version_tag": r.version_tag,
        "target_company": r.target_company,
        "target_role": r.target_role,
        "ats_score": r.ats_score,
        "bullet_count": r.bullet_count,
        "is_base_template": r.is_base_template,
        "is_generated": r.is_generated,
        "github_path": r.github_path,
        "latex_content": r.latex_content,
        "markdown_content": r.markdown_content,
        "raw_text": r.raw_text,
        "created_at": r.created_at.isoformat(),
    }


# ── Delete ─────────────────────────────────────────────────────────────────


@router.delete("/resumes/{resume_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_resume(
    resume_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Resume).where(Resume.id == resume_id, Resume.user_id == user.id)
    )
    resume = result.scalar_one_or_none()
    if not resume:
        raise HTTPException(status_code=404, detail="Resume not found")

    await db.delete(resume)
    await db.commit()


# ── Update resume metadata ─────────────────────────────────────────────────


@router.patch("/resumes/{resume_id}")
async def update_resume_metadata(
    resume_id: uuid.UUID,
    target_company: str | None = None,
    target_role: str | None = None,
    version_tag: str | None = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """
    Update editable metadata on a stored resume:
      - target_company (re-classify which company this resume is for)
      - target_role    (re-classify which role)
      - version_tag    (rename/relabel the version)
    Only provided fields are updated; omit a field to leave it unchanged.
    """
    result = await db.execute(
        select(Resume).where(Resume.id == resume_id, Resume.user_id == user.id)
    )
    resume = result.scalar_one_or_none()
    if not resume:
        raise HTTPException(status_code=404, detail="Resume not found")

    if target_company is not None:
        resume.target_company = target_company or None
    if target_role is not None:
        resume.target_role = target_role or None
    if version_tag is not None:
        resume.version_tag = version_tag or None

    await db.commit()
    await db.refresh(resume)
    return {
        "resume_id": str(resume.id),
        "target_company": resume.target_company,
        "target_role": resume.target_role,
        "version_tag": resume.version_tag,
        "updated": True,
    }


# ── Download ────────────────────────────────────────────────────────────────


@router.get("/download/{resume_id}")
async def download_resume_file(
    resume_id: uuid.UUID,
    fmt: str = "tex",  # "tex" | "markdown" | "pdf"
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    Download a resume file from the vault.

    fmt=tex       → returns the LaTeX source (.tex)
    fmt=markdown  → returns the markdown preview (.md)
    fmt=pdf       → serves the LaTeX source with a .pdf filename ({FirstName}.pdf).
                    No server-side compilation — the file is raw LaTeX.  Browsers
                    that open it in a viewer will show plain text; the primary use
                    case is triggering a "Save as … .pdf" download so the file
                    lands in the user's Downloads folder with the recruiter-friendly
                    name stored in Resume.recruiter_filename.
    """
    result = await db.execute(
        select(Resume).where(Resume.id == resume_id, Resume.user_id == user.id)
    )
    resume = result.scalar_one_or_none()
    if not resume:
        raise HTTPException(status_code=404, detail="Resume not found")

    if fmt == "markdown":
        content = resume.markdown_content or ""
        media_type = "text/markdown"
        ext = "md"
    elif fmt == "pdf":
        # MVP: serve LaTeX source renamed to {FirstName}.pdf so the download
        # lands with a recruiter-friendly filename.  No pdflatex on this host.
        content = resume.latex_content or resume.raw_text or ""
        media_type = "application/x-tex"
        ext = "pdf"
    else:
        content = resume.latex_content or resume.raw_text or ""
        media_type = "application/x-tex"
        ext = "tex"

    if not content:
        raise HTTPException(status_code=404, detail=f"No {fmt} content available for this resume")

    # recruiter_filename is stored as "{FirstName}.pdf"; swap extension to match fmt
    base_filename = resume.recruiter_filename or f"{resume.version_tag or resume.id}"
    # Strip any existing extension so we can attach the correct one
    stem = base_filename.rsplit(".", 1)[0] if "." in base_filename else base_filename
    filename = f"{stem}.{ext}"

    return Response(
        content=content.encode("utf-8"),
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ── Sync markdown (offline edit drain) ─────────────────────────────────────


@router.post("/sync-markdown")
async def sync_markdown(
    version_tag: str = Form(...),
    markdown_content: str = Form(...),
    timestamp: str = Form(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    Sync an offline markdown edit to the database.

    Called by the extension's background worker when connectivity is restored.
    Updates the resume's markdown_content in the vault so it reflects any
    offline edits the user made to their resume preview.
    """

    result = await db.execute(
        select(Resume)
        .where(
            Resume.user_id == user.id,
            Resume.version_tag == version_tag,
        )
        .order_by(Resume.created_at.desc())
        .limit(1)
    )
    resume = result.scalar_one_or_none()

    if not resume:
        raise HTTPException(
            status_code=404,
            detail=f"No resume found with version_tag={version_tag!r}",
        )

    resume.markdown_content = markdown_content
    await db.commit()

    logger.info(
        f"Synced offline markdown edit for {version_tag} " f"(ts={timestamp}, user={user.id})"
    )
    return {"synced": True, "version_tag": version_tag}
