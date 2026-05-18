"""
Portal scanner service.

Detects ATS board from URL and fetches structured JD data.
Supported: Greenhouse, Lever, Ashby.
Wellfound: deferred to v2 (requires headless browser) — returns manual_entry=True.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import httpx
from loguru import logger

from app.middleware.circuit_breaker import portal_circuit

_BOARD_PATTERNS: dict[str, re.Pattern] = {
    "greenhouse": re.compile(r"boards\.greenhouse\.io/([\w-]+)/jobs/(\d+)"),
    "lever": re.compile(r"jobs\.lever\.co/([\w-]+)/([a-f0-9-]+)"),
    "ashby": re.compile(r"jobs\.ashbyhq\.com/([\w-]+)/([^/?#]+)"),
}

_BOARD_TIMEOUTS: dict[str, httpx.Timeout] = {
    "greenhouse": httpx.Timeout(8.0, connect=3.0),
    "lever": httpx.Timeout(8.0, connect=3.0),
    "ashby": httpx.Timeout(12.0, connect=3.0),
}


@dataclass
class ScanResult:
    board_type: str
    company_slug: str
    job_id: str
    company_name: str
    title: str
    location: str
    remote_policy: str
    requirements: list[str] = field(default_factory=list)
    responsibilities: list[str] = field(default_factory=list)
    apply_url: str = ""
    compensation_min: int | None = None
    compensation_max: int | None = None
    manual_entry: bool = False


def detect_board(url: str) -> tuple[str, str, str] | None:
    """Returns (board_type, company_slug, job_id) or None if unrecognized."""
    for board, pattern in _BOARD_PATTERNS.items():
        match = pattern.search(url)
        if match:
            return board, match.group(1), match.group(2)
    return None


def _extract_compensation(text: str) -> tuple[int | None, int | None]:
    pattern = re.compile(
        r"\$\s?(\d{2,3}(?:,\d{3})?)\s*[kK]?\s*[–\-]\s*\$?\s?(\d{2,3}(?:,\d{3})?)\s*[kK]?"
    )
    match = pattern.search(text)
    if not match:
        return None, None
    try:

        def parse(s: str) -> int:
            n = int(s.replace(",", ""))
            return n * 1000 if n < 1000 else n

        return parse(match.group(1)), parse(match.group(2))
    except ValueError:
        return None, None


@portal_circuit
async def _fetch_greenhouse(company_slug: str, job_id: str, url: str) -> ScanResult:
    api_url = f"https://boards-api.greenhouse.io/v1/boards/{company_slug}/jobs/{job_id}"
    async with httpx.AsyncClient(timeout=_BOARD_TIMEOUTS["greenhouse"]) as client:
        for attempt in range(2):
            try:
                resp = await client.get(api_url)
                resp.raise_for_status()
                break
            except httpx.HTTPStatusError as e:
                if attempt == 0 and e.response.status_code >= 500:
                    continue
                raise

    data = resp.json()
    title = data.get("title", "")
    location = data.get("location", {}).get("name", "")
    content = data.get("content", "")
    dept = (data.get("departments") or [{}])[0].get("name", "")

    clean = re.sub(r"<[^>]+>", " ", content)
    lines = [ln.strip() for ln in clean.split("\n") if ln.strip() and len(ln.strip()) > 20]

    comp_min, comp_max = _extract_compensation(clean)
    remote = "remote" if "remote" in (title + location + clean).lower() else "onsite"

    return ScanResult(
        board_type="greenhouse",
        company_slug=company_slug,
        job_id=job_id,
        company_name=dept or company_slug.replace("-", " ").title(),
        title=title,
        location=location,
        remote_policy=remote,
        requirements=lines[:15],
        responsibilities=lines[:10],
        apply_url=url,
        compensation_min=comp_min,
        compensation_max=comp_max,
    )


@portal_circuit
async def _fetch_lever(company_slug: str, job_id: str, url: str) -> ScanResult:
    api_url = f"https://api.lever.co/v0/postings/{company_slug}/{job_id}"
    async with httpx.AsyncClient(timeout=_BOARD_TIMEOUTS["lever"]) as client:
        for attempt in range(2):
            try:
                resp = await client.get(api_url)
                resp.raise_for_status()
                break
            except httpx.HTTPStatusError as e:
                if attempt == 0 and e.response.status_code >= 500:
                    continue
                raise

    data = resp.json()
    title = data.get("text", "")
    location = data.get("categories", {}).get("location", "")
    commitment = data.get("categories", {}).get("commitment", "")
    content_sections = data.get("content", {})
    description = content_sections.get("descriptionBody", "")
    lists_data = content_sections.get("lists", [])

    requirements: list[str] = []
    responsibilities: list[str] = []
    for section in lists_data:
        section_text = section.get("text", "").lower()
        items = re.findall(r"<li>(.*?)</li>", section.get("content", ""), re.DOTALL)
        items = [re.sub(r"<[^>]+>", "", i).strip() for i in items]
        if "require" in section_text or "qualif" in section_text:
            requirements.extend(items)
        elif "responsib" in section_text or "what you" in section_text:
            responsibilities.extend(items)

    comp_min, comp_max = _extract_compensation(description)
    remote = "remote" if "remote" in (title + location + commitment).lower() else "onsite"

    return ScanResult(
        board_type="lever",
        company_slug=company_slug,
        job_id=job_id,
        company_name=company_slug.replace("-", " ").title(),
        title=title,
        location=location,
        remote_policy=remote,
        requirements=requirements[:15],
        responsibilities=responsibilities[:10],
        apply_url=url,
        compensation_min=comp_min,
        compensation_max=comp_max,
    )


@portal_circuit
async def _fetch_ashby(company_slug: str, job_id: str, url: str) -> ScanResult:
    api_url = f"https://jobs.ashbyhq.com/api/non-user-facing/posting-api/job-board/{company_slug}"
    async with httpx.AsyncClient(timeout=_BOARD_TIMEOUTS["ashby"]) as client:
        resp = await client.get(api_url)
        resp.raise_for_status()

    data = resp.json()
    jobs = data.get("jobPostings", [])
    target = None
    for job in jobs:
        path = job.get("jobPostingPath", "")
        if job_id.lower() in path.lower():
            target = job
            break

    if not target:
        raise ValueError(f"Job {job_id} not found in Ashby board {company_slug}")

    title = target.get("title", "")
    location = target.get("locationName", "")
    description = target.get("descriptionHtml", "")
    clean = re.sub(r"<[^>]+>", " ", description)
    lines = [ln.strip() for ln in clean.split("\n") if ln.strip() and len(ln.strip()) > 20]

    comp_min, comp_max = _extract_compensation(clean)
    remote = "remote" if "remote" in (title + location + clean).lower() else "onsite"

    return ScanResult(
        board_type="ashby",
        company_slug=company_slug,
        job_id=job_id,
        company_name=company_slug.replace("-", " ").title(),
        title=title,
        location=location,
        remote_policy=remote,
        requirements=lines[:15],
        responsibilities=lines[:10],
        apply_url=url,
        compensation_min=comp_min,
        compensation_max=comp_max,
    )


def _manual_entry(url: str) -> ScanResult:
    return ScanResult(
        board_type="manual",
        company_slug="",
        job_id="",
        company_name="",
        title="",
        location="",
        remote_policy="",
        apply_url=url,
        manual_entry=True,
    )


async def scan_url(url: str) -> ScanResult:
    """Detect board from URL and fetch. Returns manual_entry=True if unrecognized."""
    detected = detect_board(url)
    if not detected:
        return _manual_entry(url)

    board_type, company_slug, job_id = detected
    try:
        if board_type == "greenhouse":
            return await _fetch_greenhouse(company_slug, job_id, url)
        elif board_type == "lever":
            return await _fetch_lever(company_slug, job_id, url)
        elif board_type == "ashby":
            return await _fetch_ashby(company_slug, job_id, url)
    except Exception as exc:
        logger.error(f"[portal_scan] {board_type} fetch failed for {url}: {exc}")
        raise

    return _manual_entry(url)
