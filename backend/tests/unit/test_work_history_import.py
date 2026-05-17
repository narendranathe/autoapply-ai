"""
Unit tests for ``app.services.work_history_import``.

Covers:
  - GitHub repo → ``WorkHistoryEntry`` kwargs mapping
  - LinkedIn ``Profile.json`` parsing (multiple date formats + field aliases)
  - GitHub dedupe (source_url-based)
  - LinkedIn dedupe (company + title + start_date, case-insensitive)
  - ``fetch_github_repos`` HTTP flow with a mocked ``httpx.AsyncClient``
    (no network)
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.services.work_history_import import (
    WorkHistoryImportError,
    dedupe_github,
    dedupe_linkedin,
    fetch_github_repos,
    parse_linkedin_positions,
    repo_to_entry_kwargs,
)

FIXTURES_DIR = Path(__file__).parent / "fixtures"


# ─────────────────────────────────────────────────────────────────────────────
# GitHub repo → entry mapping
# ─────────────────────────────────────────────────────────────────────────────


class TestRepoToEntryKwargs:
    def test_basic_repo(self) -> None:
        repo = {
            "name": "autoapply-ai",
            "description": "Resume tailoring CLI",
            "language": "Python",
            "stargazers_count": 42,
            "html_url": "https://github.com/me/autoapply-ai",
            "created_at": "2023-04-15T12:00:00Z",
            "pushed_at": "2024-02-20T08:30:00Z",
        }
        kw = repo_to_entry_kwargs(repo)
        assert kw["role_title"] == "autoapply-ai"
        assert kw["company_name"] == ""
        assert kw["source"] == "github"
        assert kw["source_url"] == "https://github.com/me/autoapply-ai"
        assert kw["start_date"] == "2023-04-15"
        assert kw["end_date"] == "2024-02-20"
        assert kw["technologies"] == ["Python"]
        # bullets contain description + language + stars
        assert "Resume tailoring CLI" in kw["bullets"]
        assert "Primary language: Python" in kw["bullets"]
        assert "Stars: 42" in kw["bullets"]

    def test_repo_without_description_language_stars(self) -> None:
        repo = {
            "name": "empty-repo",
            "description": None,
            "language": None,
            "stargazers_count": 0,
            "html_url": "https://github.com/me/empty-repo",
            "created_at": "2024-01-01T00:00:00Z",
            "pushed_at": "",
        }
        kw = repo_to_entry_kwargs(repo)
        assert kw["bullets"] == []  # nothing to say
        assert kw["technologies"] == []
        assert kw["end_date"] is None

    def test_unnamed_repo_uses_placeholder(self) -> None:
        kw = repo_to_entry_kwargs({"name": ""})
        assert kw["role_title"] == "(unnamed repo)"
        assert kw["source"] == "github"


# ─────────────────────────────────────────────────────────────────────────────
# LinkedIn parsing
# ─────────────────────────────────────────────────────────────────────────────


class TestParseLinkedinPositions:
    def test_modern_export_format(self) -> None:
        """Newer (2023+) LinkedIn exports use ``startedOn`` / ``finishedOn``."""
        profile = {
            "positions": [
                {
                    "title": "Senior Engineer",
                    "companyName": "Acme",
                    "startedOn": {"year": 2022, "month": 6},
                    "finishedOn": {"year": 2024, "month": 3},
                    "description": "Built thing A.\nShipped thing B.",
                    "location": "San Francisco, CA",
                }
            ]
        }
        entries = parse_linkedin_positions(profile)
        assert len(entries) == 1
        e = entries[0]
        assert e["company_name"] == "Acme"
        assert e["role_title"] == "Senior Engineer"
        assert e["start_date"] == "Jun 2022"
        assert e["end_date"] == "Mar 2024"
        assert e["is_current"] is False
        assert e["bullets"] == ["Built thing A.", "Shipped thing B."]
        assert e["location"] == "San Francisco, CA"
        assert e["source"] == "linkedin"

    def test_current_position(self) -> None:
        profile = {
            "positions": [
                {
                    "title": "Founder",
                    "companyName": "MyCo",
                    "startedOn": {"year": 2024, "month": 1},
                    "finishedOn": None,
                    "description": "Doing things.",
                }
            ]
        }
        entries = parse_linkedin_positions(profile)
        assert entries[0]["is_current"] is True
        assert entries[0]["end_date"] is None

    def test_legacy_csv_style_export(self) -> None:
        """Older LinkedIn exports use ``Started On`` / ``Finished On`` (string)."""
        profile = {
            "positions": [
                {
                    "Title": "Software Engineer",
                    "Company Name": "Big Co",
                    "Started On": "Jan 2020",
                    "Finished On": "Dec 2021",
                    "Description": "Did things.",
                }
            ]
        }
        entries = parse_linkedin_positions(profile)
        assert len(entries) == 1
        assert entries[0]["role_title"] == "Software Engineer"
        assert entries[0]["company_name"] == "Big Co"
        assert entries[0]["start_date"] == "Jan 2020"
        assert entries[0]["end_date"] == "Dec 2021"

    def test_timeperiod_nested_dates(self) -> None:
        profile = {
            "positions": [
                {
                    "title": "Intern",
                    "company": "Startup",
                    "timePeriod": {
                        "startDate": {"year": 2019, "month": 5},
                        "endDate": {"year": 2019, "month": 8},
                    },
                }
            ]
        }
        entries = parse_linkedin_positions(profile)
        assert entries[0]["start_date"] == "May 2019"
        assert entries[0]["end_date"] == "Aug 2019"

    def test_empty_position_skipped(self) -> None:
        profile = {"positions": [{"title": "", "companyName": ""}]}
        assert parse_linkedin_positions(profile) == []

    def test_missing_positions_key(self) -> None:
        assert parse_linkedin_positions({}) == []
        assert parse_linkedin_positions({"positions": None}) == []
        assert parse_linkedin_positions({"positions": "not a list"}) == []

    def test_loads_real_fixture(self) -> None:
        fx = FIXTURES_DIR / "linkedin_profile.json"
        profile = json.loads(fx.read_text(encoding="utf-8"))
        entries = parse_linkedin_positions(profile)
        # Fixture has 3 positions, one empty row that should be skipped
        assert len(entries) == 3
        # Sort order is preserved (first position = sort_order 0)
        assert entries[0]["sort_order"] == 0
        # All marked as linkedin source
        assert all(e["source"] == "linkedin" for e in entries)


# ─────────────────────────────────────────────────────────────────────────────
# Dedupe
# ─────────────────────────────────────────────────────────────────────────────


class TestDedupeGithub:
    def test_skips_existing_urls(self) -> None:
        entries = [
            {"role_title": "a", "source_url": "https://github.com/me/a"},
            {"role_title": "b", "source_url": "https://github.com/me/b"},
        ]
        existing = {"https://github.com/me/a"}
        new, skipped = dedupe_github(entries, existing)
        assert skipped == 1
        assert len(new) == 1
        assert new[0]["role_title"] == "b"

    def test_dedupes_within_batch(self) -> None:
        entries = [
            {"role_title": "a", "source_url": "https://github.com/me/a"},
            {"role_title": "a-dup", "source_url": "https://github.com/me/a"},
        ]
        new, skipped = dedupe_github(entries, set())
        assert skipped == 1
        assert len(new) == 1

    def test_empty_source_url_kept(self) -> None:
        """We can't dedupe rows with no URL, so they pass through."""
        entries = [
            {"role_title": "a", "source_url": ""},
            {"role_title": "b", "source_url": None},
        ]
        new, skipped = dedupe_github(entries, set())
        assert skipped == 0
        assert len(new) == 2


class TestDedupeLinkedin:
    def test_skips_existing_keys(self) -> None:
        entries = [
            {"company_name": "Acme", "role_title": "Eng", "start_date": "Jan 2020"},
            {"company_name": "BigCo", "role_title": "SWE", "start_date": "Feb 2021"},
        ]
        existing = {("acme", "eng", "jan 2020")}
        new, skipped = dedupe_linkedin(entries, existing)
        assert skipped == 1
        assert len(new) == 1
        assert new[0]["company_name"] == "BigCo"

    def test_case_insensitive(self) -> None:
        entries = [{"company_name": "ACME", "role_title": "ENG", "start_date": "Jan 2020"}]
        existing = {("acme", "eng", "jan 2020")}
        _new, skipped = dedupe_linkedin(entries, existing)
        assert skipped == 1

    def test_dedupes_within_batch(self) -> None:
        entries = [
            {"company_name": "Acme", "role_title": "Eng", "start_date": "Jan 2020"},
            {"company_name": "Acme", "role_title": "Eng", "start_date": "Jan 2020"},
        ]
        new, skipped = dedupe_linkedin(entries, set())
        assert skipped == 1
        assert len(new) == 1


# ─────────────────────────────────────────────────────────────────────────────
# fetch_github_repos — mocked HTTP
# ─────────────────────────────────────────────────────────────────────────────


def _make_mock_client(status_code: int, payload: Any) -> MagicMock:
    """
    Build a context-manager-compatible mock ``httpx.AsyncClient`` whose
    ``.get()`` returns a response with the given status + JSON body.
    """
    mock_resp = MagicMock(spec=httpx.Response)
    mock_resp.status_code = status_code
    mock_resp.json.return_value = payload
    mock_resp.text = json.dumps(payload) if not isinstance(payload, str) else payload

    client = MagicMock()
    client.get = AsyncMock(return_value=mock_resp)
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=None)
    return client


@pytest.mark.asyncio
async def test_fetch_github_repos_success() -> None:
    """A 200 response returns the parsed repo list verbatim."""
    repos_payload = [
        {"name": "repo-1", "html_url": "https://github.com/me/repo-1"},
        {"name": "repo-2", "html_url": "https://github.com/me/repo-2"},
    ]
    mock_client = _make_mock_client(200, repos_payload)
    with patch(
        "app.services.work_history_import.decrypt_value",
        return_value="ghp_fake_token",
    ):
        repos = await fetch_github_repos(
            encrypted_token="enc",
            client_factory=lambda: mock_client,
        )
    assert repos == repos_payload
    # Auth header propagated
    call = mock_client.get.await_args
    assert call.kwargs["headers"]["Authorization"] == "token ghp_fake_token"


@pytest.mark.asyncio
async def test_fetch_github_repos_401() -> None:
    mock_client = _make_mock_client(401, {"message": "Bad credentials"})
    with (
        patch(
            "app.services.work_history_import.decrypt_value",
            return_value="ghp_fake_token",
        ),
        pytest.raises(WorkHistoryImportError, match="invalid or expired"),
    ):
        await fetch_github_repos("enc", client_factory=lambda: mock_client)


@pytest.mark.asyncio
async def test_fetch_github_repos_unexpected_shape() -> None:
    mock_client = _make_mock_client(200, {"not": "a list"})
    with (
        patch(
            "app.services.work_history_import.decrypt_value",
            return_value="ghp_fake_token",
        ),
        pytest.raises(WorkHistoryImportError, match="Unexpected"),
    ):
        await fetch_github_repos("enc", client_factory=lambda: mock_client)
