"""
Work History import service — parsers + dedupe helpers for the
GitHub and LinkedIn import endpoints (#108).

Pure logic only: no FastAPI, no DB session — easy to unit-test.
HTTP I/O against the GitHub API lives here so the router stays thin,
but a callable httpx.AsyncClient factory can be injected for tests.
"""

from __future__ import annotations

import re
import time
from collections.abc import Awaitable, Callable
from typing import Any

import httpx

from app.utils.encryption import decrypt_value


class WorkHistoryImportError(Exception):
    """Base exception for import failures (auth, parsing, rate limit)."""


class WorkHistoryAuthError(WorkHistoryImportError):
    """GitHub token is invalid or expired (HTTP 401 upstream)."""


class WorkHistoryPermissionError(WorkHistoryImportError):
    """GitHub returned a true 403 (permission denied, not rate-limit)."""


class WorkHistoryRateLimitError(WorkHistoryImportError):
    """
    Upstream rate limit hit. ``retry_after`` is seconds the caller should
    wait before retrying (computed from the ``X-RateLimit-Reset`` header).
    """

    def __init__(self, message: str = "GitHub API rate limit exceeded.", *, retry_after: int = 60):
        super().__init__(message)
        self.retry_after = max(0, int(retry_after))


# ── GitHub ─────────────────────────────────────────────────────────────────


GITHUB_API_BASE = "https://api.github.com"
GITHUB_REPOS_PATH = "/user/repos?per_page=100&sort=updated&type=owner"


def _build_github_headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def repo_to_entry_kwargs(repo: dict[str, Any]) -> dict[str, Any]:
    """
    Map a single GitHub repo JSON payload to the kwargs needed to construct
    a ``WorkHistoryEntry``.

    Title  = repo name
    Bullets = [description, "Primary language: X", "Stars: N"] (only non-empty)
    Tech   = [primary language]  (extra languages would need /languages call;
             keeping a single request per repo keeps the import cheap)
    """
    name = (repo.get("name") or "").strip() or "(unnamed repo)"
    description = (repo.get("description") or "").strip()
    language = (repo.get("language") or "").strip()
    stars = repo.get("stargazers_count") or 0
    html_url = (repo.get("html_url") or "").strip()
    created_at = (repo.get("created_at") or "")[:10]  # YYYY-MM-DD
    pushed_at = (repo.get("pushed_at") or "")[:10]

    bullets: list[str] = []
    if description:
        bullets.append(description)
    if language:
        bullets.append(f"Primary language: {language}")
    if isinstance(stars, int) and stars > 0:
        bullets.append(f"Stars: {stars}")

    technologies: list[str] = [language] if language else []

    return {
        # GitHub repositories are personal projects, not employment.
        # Mark explicitly as "project" so to_text_block/UI can render
        # appropriately (e.g. "PROJECT: my-repo on GitHub").
        "entry_type": "project",
        "company_name": "GitHub",
        "role_title": name,
        "start_date": created_at or "",
        "end_date": pushed_at or None,
        "is_current": False,
        "bullets": bullets,
        "technologies": technologies,
        "source": "github",
        "source_url": html_url or None,
    }


async def fetch_github_repos(
    encrypted_token: str,
    *,
    client_factory: Callable[[], httpx.AsyncClient] | None = None,
) -> list[dict[str, Any]]:
    """
    Fetch the authenticated user's repositories from the GitHub API.

    ``client_factory`` lets tests inject a mock httpx client. Default is a
    real ``httpx.AsyncClient`` with a 15s timeout (matches GitHubService).
    """
    try:
        token = decrypt_value(encrypted_token)
    except Exception as exc:  # pragma: no cover - exercised via 401 path
        raise WorkHistoryImportError(f"Failed to decrypt GitHub token: {exc}") from exc

    if client_factory is None:

        def _default_factory() -> httpx.AsyncClient:
            return httpx.AsyncClient(timeout=15.0)

        client_factory = _default_factory

    async with client_factory() as client:
        resp = await client.get(
            f"{GITHUB_API_BASE}{GITHUB_REPOS_PATH}",
            headers=_build_github_headers(token),
        )
        if resp.status_code == 401:
            raise WorkHistoryAuthError("GitHub token is invalid or expired. Reconnect in settings.")
        if resp.status_code == 403:
            # Distinguish rate-limit (X-RateLimit-Remaining: 0) from a true
            # permission denial. GitHub uses 403 for both — the header is
            # the only reliable signal.
            remaining = resp.headers.get("X-RateLimit-Remaining")
            if remaining == "0":
                try:
                    reset_ts = int(resp.headers.get("X-RateLimit-Reset", "0"))
                except (TypeError, ValueError):
                    reset_ts = 0
                retry_after = reset_ts - int(time.time()) if reset_ts else 60
                raise WorkHistoryRateLimitError(
                    "GitHub API rate limit exceeded. Try again later.",
                    retry_after=retry_after,
                )
            raise WorkHistoryPermissionError(f"GitHub API permission denied: {resp.text[:200]}")
        if resp.status_code >= 400:
            raise WorkHistoryImportError(f"GitHub API error {resp.status_code}: {resp.text[:200]}")
        data = resp.json()
        if not isinstance(data, list):
            raise WorkHistoryImportError("Unexpected GitHub API response shape.")
        return data


# ── LinkedIn ───────────────────────────────────────────────────────────────


# Upload + parsing safety caps. LinkedIn Profile.json exports are typically
# under 1 MB and contain at most a few dozen positions; numbers well above
# these reflect either bad input or a DoS attempt.
MAX_LINKEDIN_FILE_BYTES = 5 * 1024 * 1024  # 5 MB
MAX_LINKEDIN_POSITIONS = 500
MAX_BULLET_CHARS = 500
MAX_BULLETS_PER_POSITION = 20


# Control chars (excluding tab/newline/CR), zero-width chars, bidi overrides:
# these are common prompt-injection vectors when the description is later
# concatenated into an LLM prompt.
_CONTROL_CHAR_RE = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")
_ZERO_WIDTH_RE = re.compile("[​-‏‪-‮⁠-⁩]")
# Prompt-injection sentinels: lines starting with role markers like
# "system:", "assistant:", "user:", or with "<|" tags used by chat templates.
_PROMPT_INJECTION_RE = re.compile(r"(?i)^(?:system|assistant|user)\s*:\s*")


def _sanitize_bullet(text: str) -> str | None:
    """
    Clean a LinkedIn description bullet before it reaches any LLM prompt.

    Returns None for bullets that should be dropped entirely (e.g. lines that
    look like a prompt-injection role marker).
    """
    if not text:
        return None
    cleaned = _CONTROL_CHAR_RE.sub("", text)
    cleaned = _ZERO_WIDTH_RE.sub("", cleaned)
    cleaned = cleaned.strip()
    if not cleaned:
        return None
    # Drop obvious prompt-injection lines outright rather than try to neutralize
    if _PROMPT_INJECTION_RE.match(cleaned):
        return None
    if cleaned.startswith("<|"):
        return None
    if len(cleaned) > MAX_BULLET_CHARS:
        cleaned = cleaned[: MAX_BULLET_CHARS - 3].rstrip() + "..."
    return cleaned


def _linkedin_date_to_string(date_obj: Any) -> str:
    """
    LinkedIn export dates look like ``{"year": 2023, "month": 4}`` or
    ``"Apr 2023"`` or ``""``. Normalize to a human-readable string.
    """
    if not date_obj:
        return ""
    if isinstance(date_obj, str):
        return date_obj.strip()
    if isinstance(date_obj, dict):
        year = date_obj.get("year")
        month = date_obj.get("month")
        if year and month:
            months = [
                "Jan",
                "Feb",
                "Mar",
                "Apr",
                "May",
                "Jun",
                "Jul",
                "Aug",
                "Sep",
                "Oct",
                "Nov",
                "Dec",
            ]
            try:
                return f"{months[int(month) - 1]} {int(year)}"
            except (ValueError, IndexError):
                return f"{year}"
        if year:
            return str(year)
    return ""


def parse_linkedin_positions(profile: dict[str, Any]) -> list[dict[str, Any]]:
    """
    Map LinkedIn ``Profile.json`` ``positions`` array → list of
    ``WorkHistoryEntry`` kwarg dicts.

    LinkedIn exports use a few different field-name conventions across years
    of dumps. We accept the most common variants seen in the wild:
      title         | name
      companyName   | company | organization
      startedOn     | startDate | timePeriod.startDate
      finishedOn    | endDate   | timePeriod.endDate
      description   | summary
    """
    positions = profile.get("positions") or profile.get("Positions") or []
    if not isinstance(positions, list):
        return []

    entries: list[dict[str, Any]] = []
    for idx, pos in enumerate(positions):
        if not isinstance(pos, dict):
            continue

        title = (pos.get("title") or pos.get("name") or pos.get("Title") or "").strip()
        company = (
            pos.get("companyName")
            or pos.get("company")
            or pos.get("organization")
            or pos.get("Company Name")
            or ""
        ).strip()

        start_raw = (
            pos.get("startedOn")
            or pos.get("startDate")
            or (pos.get("timePeriod") or {}).get("startDate")
            or pos.get("Started On")
            or ""
        )
        end_raw = (
            pos.get("finishedOn")
            or pos.get("endDate")
            or (pos.get("timePeriod") or {}).get("endDate")
            or pos.get("Finished On")
            or ""
        )
        start_date = _linkedin_date_to_string(start_raw)
        end_date = _linkedin_date_to_string(end_raw)
        is_current = not bool(end_date)

        description = (
            pos.get("description") or pos.get("summary") or pos.get("Description") or ""
        ).strip()
        bullets: list[str] = []
        for line in description.splitlines():
            cleaned = _sanitize_bullet(line)
            if cleaned is None:
                continue
            bullets.append(cleaned)
            if len(bullets) >= MAX_BULLETS_PER_POSITION:
                break

        location = pos.get("location") or pos.get("Location") or None
        if isinstance(location, str):
            location = location.strip() or None

        if not company and not title:
            # Skip empty rows — LinkedIn occasionally exports blanks
            continue

        entries.append(
            {
                "entry_type": "work",
                "company_name": company,
                "role_title": title,
                "start_date": start_date,
                "end_date": end_date or None,
                "is_current": is_current,
                "location": location,
                "bullets": bullets,
                "technologies": [],
                "sort_order": idx,
                "source": "linkedin",
                "source_url": None,
            }
        )

    return entries


# ── Dedupe helpers ─────────────────────────────────────────────────────────


def dedupe_github(
    entries_to_add: list[dict[str, Any]],
    existing_source_urls: set[str],
) -> tuple[list[dict[str, Any]], int]:
    """
    Return (new_entries, skipped_count).
    Dedupe key: source_url (repo html_url). Entries with empty source_url
    are kept (we can't dedupe them) and counted as new.
    """
    new_entries: list[dict[str, Any]] = []
    skipped = 0
    seen: set[str] = set()
    for e in entries_to_add:
        url = (e.get("source_url") or "").strip()
        if url:
            if url in existing_source_urls or url in seen:
                skipped += 1
                continue
            seen.add(url)
        new_entries.append(e)
    return new_entries, skipped


def dedupe_linkedin(
    entries_to_add: list[dict[str, Any]],
    existing_keys: set[tuple[str, str, str]],
) -> tuple[list[dict[str, Any]], int]:
    """
    Return (new_entries, skipped_count).
    Dedupe key: (company_name, role_title, start_date) — case-insensitive
    on company and title to absorb minor LinkedIn formatting drift.
    """
    new_entries: list[dict[str, Any]] = []
    skipped = 0
    seen: set[tuple[str, str, str]] = set()
    for e in entries_to_add:
        key = (
            (e.get("company_name") or "").strip().lower(),
            (e.get("role_title") or "").strip().lower(),
            (e.get("start_date") or "").strip().lower(),
        )
        if key in existing_keys or key in seen:
            skipped += 1
            continue
        seen.add(key)
        new_entries.append(e)
    return new_entries, skipped


# Reusable type alias used by the router to inject a fake fetcher in tests.
GitHubRepoFetcher = Callable[[str], Awaitable[list[dict[str, Any]]]]


__all__ = [
    "GITHUB_API_BASE",
    "GITHUB_REPOS_PATH",
    "MAX_BULLET_CHARS",
    "MAX_BULLETS_PER_POSITION",
    "MAX_LINKEDIN_FILE_BYTES",
    "MAX_LINKEDIN_POSITIONS",
    "GitHubRepoFetcher",
    "WorkHistoryAuthError",
    "WorkHistoryImportError",
    "WorkHistoryPermissionError",
    "WorkHistoryRateLimitError",
    "dedupe_github",
    "dedupe_linkedin",
    "fetch_github_repos",
    "parse_linkedin_positions",
    "repo_to_entry_kwargs",
]
