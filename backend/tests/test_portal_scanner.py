"""Portal scanner unit tests — board detection, mock HTTP responses, cache behavior."""

import pytest
from pytest_httpx import HTTPXMock

from app.services.portal_scanner_service import detect_board, scan_url


def test_detect_greenhouse():
    url = "https://boards.greenhouse.io/databricks/jobs/7892341"
    result = detect_board(url)
    assert result is not None
    board, slug, job_id = result
    assert board == "greenhouse"
    assert slug == "databricks"
    assert job_id == "7892341"


def test_detect_lever():
    url = "https://jobs.lever.co/openai/abc123de-4567-89ef-ghij-klmnopqrstuv"
    result = detect_board(url)
    assert result is not None
    board, slug, job_id = result
    assert board == "lever"
    assert slug == "openai"


def test_detect_ashby():
    url = "https://jobs.ashbyhq.com/anthropic/senior-data-engineer"
    result = detect_board(url)
    assert result is not None
    board, slug, job_id = result
    assert board == "ashby"
    assert slug == "anthropic"
    assert job_id == "senior-data-engineer"


def test_detect_unrecognized_returns_none():
    url = "https://careers.workday.com/jobs/12345"
    assert detect_board(url) is None


def test_detect_wellfound_returns_none():
    """Wellfound is deferred to v2 — detect_board returns None."""
    url = "https://wellfound.com/jobs/123456"
    assert detect_board(url) is None


@pytest.mark.asyncio
async def test_scan_unrecognized_url_returns_manual_entry():
    result = await scan_url("https://careers.example.com/jobs/12345")
    assert result.manual_entry is True
    assert result.board_type == "manual"


@pytest.mark.asyncio
async def test_scan_greenhouse_mock(httpx_mock: HTTPXMock):
    """Mock Greenhouse API response and verify ScanResult parsing."""
    httpx_mock.add_response(
        url="https://boards-api.greenhouse.io/v1/boards/databricks/jobs/7892341",
        json={
            "title": "Senior Data Engineer",
            "location": {"name": "Remote - US"},
            "content": "<p>We need Spark and Kafka experience.</p><p>5+ years required.</p>",
            "departments": [{"name": "Engineering"}],
        },
    )

    result = await scan_url("https://boards.greenhouse.io/databricks/jobs/7892341")

    assert result.manual_entry is False
    assert result.board_type == "greenhouse"
    assert result.title == "Senior Data Engineer"
    assert result.location == "Remote - US"
    assert result.company_slug == "databricks"
    assert result.job_id == "7892341"


@pytest.mark.asyncio
async def test_scan_lever_mock(httpx_mock: HTTPXMock):
    """Mock Lever API response."""
    job_uuid = "abc123de-4567-89ef-0000-aabbccddeeff"
    httpx_mock.add_response(
        url="https://api.lever.co/v0/postings/openai/abc123de-4567-89ef-0000-aabbccddeeff",
        json={
            "text": "ML Platform Engineer",
            "categories": {"location": "San Francisco, CA", "commitment": "Full-time"},
            "content": {
                "descriptionBody": "Join our ML team.",
                "lists": [
                    {
                        "text": "Requirements",
                        "content": "<li>5+ years Python</li><li>MLflow experience</li>",
                    }
                ],
            },
        },
    )

    result = await scan_url(f"https://jobs.lever.co/openai/{job_uuid}")
    assert result.board_type == "lever"
    assert result.title == "ML Platform Engineer"
    assert "5+ years Python" in result.requirements


@pytest.mark.asyncio
async def test_scan_ashby_mock(httpx_mock: HTTPXMock):
    """Mock Ashby API — list response, finds job by slug."""
    httpx_mock.add_response(
        url="https://jobs.ashbyhq.com/api/non-user-facing/posting-api/job-board/anthropic",
        json={
            "jobPostings": [
                {
                    "title": "Senior Data Engineer",
                    "locationName": "Remote",
                    "jobPostingPath": "/anthropic/senior-data-engineer",
                    "descriptionHtml": "<p>Build ML infrastructure. 40% latency reduction target.</p>",
                }
            ]
        },
    )

    result = await scan_url("https://jobs.ashbyhq.com/anthropic/senior-data-engineer")
    assert result.board_type == "ashby"
    assert result.title == "Senior Data Engineer"
    assert result.job_id == "senior-data-engineer"
