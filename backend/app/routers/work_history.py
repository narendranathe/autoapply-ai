"""
Work History Router — CRUD for structured employment + education history.

Endpoints:
  GET    /api/v1/work-history                    List all entries for the current user
  POST   /api/v1/work-history                    Create a new entry
  PATCH  /api/v1/work-history/{id}               Update an entry
  DELETE /api/v1/work-history/{id}               Delete an entry
  GET    /api/v1/work-history/text               Formatted text block for LLM injection
  POST   /api/v1/work-history/seed               Bulk-create entries (idempotent on company+role)
  POST   /api/v1/work-history/import-from-resume Parse resume PDF/DOCX → auto-create entries
  POST   /api/v1/work-history/import/github      Import public repos from GitHub
  POST   /api/v1/work-history/import/linkedin    Import positions from LinkedIn Profile.json
"""

import json
import re
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from loguru import logger
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user, get_db
from app.models.user import User
from app.models.work_history import WorkHistoryEntry
from app.services.resume_generator import (
    _call_anthropic,
    _call_gemini,
    _call_groq,
    _call_kimi,
    _call_openai,
)
from app.services.resume_parser import ResumeParser
from app.services.work_history_import import (
    MAX_LINKEDIN_FILE_BYTES,
    MAX_LINKEDIN_POSITIONS,
    WorkHistoryAuthError,
    WorkHistoryImportError,
    WorkHistoryPermissionError,
    WorkHistoryRateLimitError,
    dedupe_github,
    dedupe_linkedin,
    fetch_github_repos,
    parse_linkedin_positions,
    repo_to_entry_kwargs,
)

_resume_parser = ResumeParser()

router = APIRouter()


# ── Pydantic schemas ───────────────────────────────────────────────────────


class WorkHistoryEntryIn(BaseModel):
    entry_type: str = "work"
    company_name: str
    role_title: str
    start_date: str
    end_date: str | None = None
    is_current: bool = False
    location: str | None = None
    bullets: list[str] = []
    technologies: list[str] = []
    team_size: int | None = None
    sort_order: int = 0


class WorkHistoryEntryOut(WorkHistoryEntryIn):
    id: str
    created_at: str
    updated_at: str

    class Config:
        from_attributes = True


# ── Helpers ────────────────────────────────────────────────────────────────


async def _get_entry(entry_id: str, user_id: uuid.UUID, db: AsyncSession) -> WorkHistoryEntry:
    stmt = select(WorkHistoryEntry).where(
        WorkHistoryEntry.id == uuid.UUID(entry_id),
        WorkHistoryEntry.user_id == user_id,
    )
    result = await db.execute(stmt)
    entry = result.scalar_one_or_none()
    if entry is None:
        raise HTTPException(status_code=404, detail="Entry not found")
    return entry


def _format_work_history_text(entries: list[WorkHistoryEntry]) -> str:
    """Format all entries into a dense text block for LLM injection."""
    if not entries:
        return ""
    blocks = [e.to_text_block() for e in entries]
    return "\n\n".join(blocks)


# ── Endpoints ──────────────────────────────────────────────────────────────


@router.get("/text")
async def get_work_history_text(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Return formatted work history as a single text block for LLM injection."""
    stmt = (
        select(WorkHistoryEntry)
        .where(WorkHistoryEntry.user_id == user.id)
        .order_by(WorkHistoryEntry.sort_order, WorkHistoryEntry.created_at.desc())
    )
    result = await db.execute(stmt)
    entries = list(result.scalars().all())
    return {"text": _format_work_history_text(entries), "entry_count": len(entries)}


@router.get("")
async def list_work_history(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """List all work history entries for the current user."""
    stmt = (
        select(WorkHistoryEntry)
        .where(WorkHistoryEntry.user_id == user.id)
        .order_by(WorkHistoryEntry.sort_order, WorkHistoryEntry.created_at.desc())
    )
    result = await db.execute(stmt)
    entries = list(result.scalars().all())
    return {
        "entries": [
            {
                "id": str(e.id),
                "entry_type": e.entry_type,
                "company_name": e.company_name,
                "role_title": e.role_title,
                "start_date": e.start_date,
                "end_date": e.end_date,
                "is_current": e.is_current,
                "location": e.location,
                "bullets": e.bullets,
                "technologies": e.technologies,
                "team_size": e.team_size,
                "sort_order": e.sort_order,
                "created_at": e.created_at.isoformat(),
            }
            for e in entries
        ],
        "total": len(entries),
    }


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_work_history_entry(
    payload: WorkHistoryEntryIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Create a new work history entry."""
    entry = WorkHistoryEntry(
        user_id=user.id,
        **payload.model_dump(),
    )
    db.add(entry)
    await db.commit()
    await db.refresh(entry)
    return {"id": str(entry.id), "created": True}


@router.patch("/{entry_id}")
async def update_work_history_entry(
    entry_id: str,
    payload: WorkHistoryEntryIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Update a work history entry."""
    entry = await _get_entry(entry_id, user.id, db)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(entry, field, value)
    await db.commit()
    return {"id": entry_id, "updated": True}


@router.delete("/{entry_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_work_history_entry(
    entry_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Delete a work history entry."""
    entry = await _get_entry(entry_id, user.id, db)
    await db.delete(entry)
    await db.commit()


@router.post("/seed", status_code=status.HTTP_201_CREATED)
async def seed_work_history(
    entries: list[WorkHistoryEntryIn],
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    Bulk-create entries. Skips any entry where (company_name, role_title) already exists
    for this user — idempotent re-seeding.
    """
    # Fetch existing (company, role) pairs
    stmt = select(WorkHistoryEntry.company_name, WorkHistoryEntry.role_title).where(
        WorkHistoryEntry.user_id == user.id
    )
    result = await db.execute(stmt)
    existing = {(r.company_name, r.role_title) for r in result.all()}

    created = 0
    for e in entries:
        key = (e.company_name, e.role_title)
        if key in existing:
            continue
        db.add(WorkHistoryEntry(user_id=user.id, **e.model_dump()))
        created += 1

    await db.commit()
    return {"created": created, "skipped": len(entries) - created}


# ── Import from Resume ─────────────────────────────────────────────────────


def _extract_contact_info(text: str) -> dict:
    """
    Regex-based extraction of contact fields from resume raw text.
    Returns only fields that were confidently detected.
    """
    info: dict = {}

    # Email
    email_m = re.search(r"[\w.+\-]+@[\w\-]+\.[a-z]{2,}", text, re.IGNORECASE)
    if email_m:
        info["email"] = email_m.group(0)

    # Phone — various formats
    phone_m = re.search(
        r"(?:\+?1[\s.-]?)?\(?\d{3}\)?[\s.\-]?\d{3}[\s.\-]?\d{4}",
        text,
    )
    if phone_m:
        info["phone"] = re.sub(r"[^\d+]", "", phone_m.group(0))

    # LinkedIn URL
    li_m = re.search(r"linkedin\.com/in/[\w\-]+", text, re.IGNORECASE)
    if li_m:
        info["linkedinUrl"] = f"https://{li_m.group(0)}"

    # GitHub URL
    gh_m = re.search(r"github\.com/[\w\-]+", text, re.IGNORECASE)
    if gh_m:
        info["githubUrl"] = f"https://{gh_m.group(0)}"

    # Portfolio / personal website (simple heuristic — not email, not linkedin/github)
    site_m = re.search(
        r"https?://(?!.*linkedin|.*github|.*mail)[\w\-]+\.[a-z]{2,}(?:/[\w\-./]*)?",
        text,
        re.IGNORECASE,
    )
    if site_m:
        info["portfolioUrl"] = site_m.group(0)

    # Name — first non-empty line that looks like a proper name (2-4 words, title-cased)
    for line in text.split("\n")[:10]:
        line = line.strip()
        if not line or "@" in line or re.search(r"\d", line):
            continue
        words = line.split()
        if 2 <= len(words) <= 4 and all(w[0].isupper() for w in words if w.isalpha()):
            info["firstName"] = words[0]
            info["lastName"] = words[-1]
            break

    return info


_IMPORT_SYSTEM = """You are a structured data extractor specializing in resumes.

Given resume text, extract ALL work experience entries (jobs, internships, co-ops).
Return a JSON array — nothing else, no markdown, no commentary.

Each entry must have these exact fields:
{
  "company_name": string,
  "role_title": string,
  "start_date": string,     // e.g. "July 2022" or "Jan 2020"
  "end_date": string|null,  // null if current position
  "is_current": boolean,
  "location": string|null,
  "bullets": [string],      // achievement bullets from the resume
  "technologies": [string], // tech/tools mentioned in this role
  "sort_order": number      // 0 = most recent, ascending
}

Rules:
- Only include WORK entries (skip education, certifications, projects)
- Preserve bullet text exactly as written — do not rephrase
- Technologies: extract from bullets + any tech listed under the role
- If no location is mentioned, set null
- If the role appears to be current (no end date / "Present"), set is_current=true and end_date=null
- Assign sort_order 0 to the most recent role, incrementing by 1 for older roles
"""


@router.post("/import-from-resume", status_code=status.HTTP_201_CREATED)
async def import_work_history_from_resume(
    file: UploadFile = File(...),
    providers_json: str = Form(""),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    Parse a resume PDF or DOCX and auto-create WorkHistoryEntry rows.
    Uses LLM to extract structured data; falls back to raw parser output.
    Skips entries where (company_name, role_title) already exist for this user.
    """
    file_bytes = await file.read()
    filename = file.filename or "resume"
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "unknown"

    if ext not in {"pdf", "docx", "txt"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported file type: {ext}. Supported: pdf, docx, txt",
        )

    # Step 1: parse resume to raw text
    raw_text = ""
    try:
        if ext == "pdf":
            parse_result = _resume_parser.parse_pdf(file_bytes)
            raw_text = parse_result.raw_text
        elif ext == "docx":
            parse_result = _resume_parser.parse_docx(file_bytes)
            raw_text = parse_result.raw_text
        else:
            raw_text = file_bytes.decode("utf-8", errors="replace")
    except Exception as e:
        logger.warning(f"Resume parse error for {filename}: {e}")
        raw_text = file_bytes.decode("utf-8", errors="replace")

    if not raw_text.strip():
        raise HTTPException(status_code=400, detail="Could not extract text from resume file.")

    # Step 2: LLM extraction — try providers in order
    providers: list[dict] = []
    if providers_json:
        try:
            providers = json.loads(providers_json)
        except Exception:
            providers = []

    user_prompt = f"Resume text:\n\n{raw_text[:8000]}"  # cap to avoid token overflow

    extracted_json: str | None = None
    used_provider = "rule_based"

    for p in providers:
        name = (p.get("name") or "").lower()
        api_key = p.get("api_key") or ""
        if not api_key:
            continue
        try:
            if name == "anthropic":
                extracted_json = await _call_anthropic(_IMPORT_SYSTEM, user_prompt, api_key)
            elif name == "openai":
                extracted_json = await _call_openai(_IMPORT_SYSTEM, user_prompt, api_key)
            elif name == "gemini":
                extracted_json = await _call_gemini(_IMPORT_SYSTEM, user_prompt, api_key)
            elif name == "groq":
                extracted_json = await _call_groq(_IMPORT_SYSTEM, user_prompt, api_key)
            elif name == "kimi":
                extracted_json = await _call_kimi(_IMPORT_SYSTEM, user_prompt, api_key)
            if extracted_json:
                used_provider = name
                break
        except Exception as e:
            logger.warning(f"[import-from-resume] {name} failed: {e}")
            continue

    # Step 3: parse LLM JSON or fall back to rule-based extraction
    extracted_entries: list[dict] = []
    if extracted_json:
        # Strip markdown fences if present
        cleaned = extracted_json.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[-1]
            cleaned = cleaned.rsplit("```", 1)[0]
        try:
            extracted_entries = json.loads(cleaned)
            if not isinstance(extracted_entries, list):
                extracted_entries = []
        except Exception:
            logger.warning("[import-from-resume] JSON parse failed, using rule-based fallback")
            extracted_entries = []

    if not extracted_entries:
        # Rule-based fallback: use bullets already grouped by company/role from the parser
        used_provider = "rule_based"
        try:
            if ext in {"pdf", "docx"}:
                ast = (
                    _resume_parser.parse_pdf(file_bytes)
                    if ext == "pdf"
                    else _resume_parser.parse_docx(file_bytes)
                )
                from app.services.resume_parser import ResumeSection

                exp_bullets = ast.bullets_by_section(ResumeSection.EXPERIENCE)
                # Group by company
                groups: dict[str, dict] = {}
                for b in exp_bullets:
                    key = f"{b.company or 'Unknown'}||{b.role or 'Unknown'}"
                    if key not in groups:
                        groups[key] = {
                            "company_name": b.company or "Unknown",
                            "role_title": b.role or "Unknown",
                            "start_date": b.dates.split("–")[0].strip() if b.dates else "",
                            "end_date": None,
                            "is_current": False,
                            "location": None,
                            "bullets": [],
                            "technologies": [],
                            "sort_order": len(groups),
                        }
                    groups[key]["bullets"].append(b.text)
                extracted_entries = list(groups.values())
        except Exception as e:
            logger.warning(f"[import-from-resume] rule-based fallback failed: {e}")

    if not extracted_entries:
        raise HTTPException(
            status_code=422,
            detail="Could not extract work history from this resume. Please add entries manually.",
        )

    # Step 4: seed — idempotent on (company_name, role_title)
    stmt = select(WorkHistoryEntry.company_name, WorkHistoryEntry.role_title).where(
        WorkHistoryEntry.user_id == user.id
    )
    result = await db.execute(stmt)
    existing = {(r.company_name, r.role_title) for r in result.all()}

    created = 0
    skipped = 0
    for entry in extracted_entries:
        company = str(entry.get("company_name") or "").strip()
        role = str(entry.get("role_title") or "").strip()
        if not company or not role:
            continue
        if (company, role) in existing:
            skipped += 1
            continue
        db.add(
            WorkHistoryEntry(
                user_id=user.id,
                entry_type="work",
                company_name=company,
                role_title=role,
                start_date=str(entry.get("start_date") or ""),
                end_date=entry.get("end_date") or None,
                is_current=bool(entry.get("is_current", False)),
                location=entry.get("location") or None,
                bullets=entry.get("bullets") or [],
                technologies=entry.get("technologies") or [],
                sort_order=int(entry.get("sort_order") or 0),
            )
        )
        created += 1

    await db.commit()

    # Extract contact info from raw text for the extension to optionally save to profile
    contact_info = _extract_contact_info(raw_text)

    logger.info(
        f"[import-from-resume] user={user.id} created={created} skipped={skipped} provider={used_provider}"
    )
    return {
        "created": created,
        "skipped": skipped,
        "total_extracted": len(extracted_entries),
        "provider_used": used_provider,
        "detected_profile": contact_info,  # extension can pre-fill profile fields
    }


# ── Import from GitHub ─────────────────────────────────────────────────────


@router.post("/import/github", status_code=status.HTTP_201_CREATED)
async def import_work_history_from_github(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    Import the authenticated user's public repositories from GitHub.

    Each repo becomes a ``WorkHistoryEntry(source='github')`` with the repo
    name as the title and the description + primary language as bullets.
    Deduplication key is the repo ``html_url`` stored in ``source_url`` —
    re-running the endpoint is a no-op once a repo is imported.

    Error mapping:
      * 401 — token invalid/expired (re-auth)
      * 403 — true permission denied (token lacks ``repo`` scope, etc.)
      * 429 — GitHub rate limit; ``Retry-After`` header is set
      * 502 — any other upstream failure
    """
    if not user.encrypted_github_token:
        raise HTTPException(
            status_code=400,
            detail="No GitHub token configured. Add your token via /api/v1/users/github-token.",
        )

    try:
        repos = await fetch_github_repos(user.encrypted_github_token)
    except WorkHistoryAuthError as exc:
        logger.warning(f"[import/github] user={user.id} auth failed: {exc}")
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except WorkHistoryRateLimitError as exc:
        logger.warning(
            f"[import/github] user={user.id} rate-limited, retry_after={exc.retry_after}s"
        )
        # FastAPI forwards the ``headers`` kwarg straight to the response.
        raise HTTPException(
            status_code=429,
            detail=str(exc),
            headers={"Retry-After": str(exc.retry_after)},
        ) from exc
    except WorkHistoryPermissionError as exc:
        logger.warning(f"[import/github] user={user.id} permission denied: {exc}")
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except WorkHistoryImportError as exc:
        logger.warning(f"[import/github] user={user.id} fetch failed: {exc}")
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    # Existing dedupe set: any github-sourced row this user already has
    stmt = select(WorkHistoryEntry.source_url).where(
        WorkHistoryEntry.user_id == user.id,
        WorkHistoryEntry.source == "github",
        WorkHistoryEntry.source_url.is_not(None),
    )
    result = await db.execute(stmt)
    existing_urls = {row[0] for row in result.all() if row[0]}

    candidates = [repo_to_entry_kwargs(r) for r in repos]
    new_entries, skipped = dedupe_github(candidates, existing_urls)

    for kwargs in new_entries:
        db.add(WorkHistoryEntry(user_id=user.id, **kwargs))

    # Two concurrent calls can both pass the dedupe check above (e.g. a double-click)
    # and try to insert the same (user_id, source_url) row. The partial unique index
    # added in migration ``b7c1d2e3f4a5`` makes the second commit fail with
    # IntegrityError — treat it as "another concurrent call already created it"
    # and report all candidates as skipped.
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        logger.info(
            f"[import/github] user={user.id} concurrent insert hit unique index; "
            f"treating as skipped ({exc.__class__.__name__})"
        )
        skipped += len(new_entries)
        new_entries = []

    logger.info(
        f"[import/github] user={user.id} created={len(new_entries)} skipped={skipped} "
        f"total_repos={len(repos)}"
    )
    return {"created": len(new_entries), "skipped": skipped}


# ── Import from LinkedIn ───────────────────────────────────────────────────


@router.post("/import/linkedin", status_code=status.HTTP_201_CREATED)
async def import_work_history_from_linkedin(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    Import positions from a LinkedIn ``Profile.json`` export.

    Each entry in ``positions[]`` becomes a ``WorkHistoryEntry(source='linkedin')``.
    Dedupe key: (company_name, role_title, start_date) — case-insensitive.

    Upload limits (anti-DoS):
      * file size <= ``MAX_LINKEDIN_FILE_BYTES`` (5 MB)
      * positions count <= ``MAX_LINKEDIN_POSITIONS`` (500)
    Anything larger is rejected with 413.
    """
    # Read with a hard cap (one byte over the limit so we can detect overflow
    # without slurping arbitrarily large bodies into memory).
    raw = await file.read(MAX_LINKEDIN_FILE_BYTES + 1)
    if len(raw) > MAX_LINKEDIN_FILE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="Profile.json too large; LinkedIn exports are typically <1 MB.",
        )
    if not raw:
        raise HTTPException(status_code=400, detail="Empty file upload.")
    try:
        profile = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Could not parse Profile.json: {exc}",
        ) from exc

    if not isinstance(profile, dict):
        raise HTTPException(status_code=400, detail="Profile.json must be a JSON object.")

    raw_positions = profile.get("positions") or profile.get("Positions") or []
    if isinstance(raw_positions, list) and len(raw_positions) > MAX_LINKEDIN_POSITIONS:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=(
                f"Profile contains too many positions "
                f"(>{MAX_LINKEDIN_POSITIONS}); please split the import."
            ),
        )

    candidates = parse_linkedin_positions(profile)
    if not candidates:
        return {"created": 0, "skipped": 0}

    # Existing dedupe set: every (company, title, start) the user has, lower-cased
    stmt = select(
        WorkHistoryEntry.company_name,
        WorkHistoryEntry.role_title,
        WorkHistoryEntry.start_date,
    ).where(WorkHistoryEntry.user_id == user.id)
    result = await db.execute(stmt)
    existing_keys = {
        (
            (row.company_name or "").strip().lower(),
            (row.role_title or "").strip().lower(),
            (row.start_date or "").strip().lower(),
        )
        for row in result.all()
    }

    new_entries, skipped = dedupe_linkedin(candidates, existing_keys)

    for kwargs in new_entries:
        db.add(WorkHistoryEntry(user_id=user.id, **kwargs))

    try:
        await db.commit()
    except IntegrityError as exc:
        # LinkedIn entries don't carry a source_url so the partial unique index
        # rarely fires here, but a future migration adding a (user, company,
        # role, start) constraint would surface the same race. Swallow it.
        await db.rollback()
        logger.info(
            f"[import/linkedin] user={user.id} concurrent insert hit unique index; "
            f"treating as skipped ({exc.__class__.__name__})"
        )
        skipped += len(new_entries)
        new_entries = []

    logger.info(
        f"[import/linkedin] user={user.id} created={len(new_entries)} skipped={skipped} "
        f"total_positions={len(candidates)}"
    )
    return {"created": len(new_entries), "skipped": skipped}
