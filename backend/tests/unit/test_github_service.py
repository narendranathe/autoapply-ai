"""
Tests for GitHub Service.

Uses mocked HTTP responses — no real GitHub API calls.
Tests the logic: path sanitization, file commit flow,
error handling, and similar application detection.
"""

import pytest

from app.services.github_service import GitHubService


@pytest.fixture
def github_service():
    return GitHubService()


class TestPathSanitization:
    """Test that company/role names become safe directory names."""

    def test_basic_sanitization(self, github_service):
        assert github_service._sanitize_path("Google") == "google"

    def test_spaces_to_dashes(self, github_service):
        assert github_service._sanitize_path("Meta Platforms") == "meta-platforms"

    def test_special_chars_removed(self, github_service):
        assert github_service._sanitize_path("AT&T Inc.") == "att-inc"

    def test_multiple_spaces_collapsed(self, github_service):
        result = github_service._sanitize_path("  Senior   ML   Engineer  ")
        assert result == "senior-ml-engineer"

    def test_slashes_removed(self, github_service):
        result = github_service._sanitize_path("Frontend/Backend Engineer")
        assert "/" not in result
        assert "\\" not in result

    def test_unicode_handled(self, github_service):
        result = github_service._sanitize_path("Über Technologies")
        assert len(result) > 0
        # Should contain only safe chars
        import re

        assert re.match(r"^[a-z0-9-]+$", result)

    def test_empty_string(self, github_service):
        result = github_service._sanitize_path("")
        assert result == ""

    def test_long_names_not_truncated_by_sanitize(self, github_service):
        long_name = "A" * 100
        result = github_service._sanitize_path(long_name)
        # Sanitize doesn't truncate — the caller handles max length
        assert len(result) == 100


class TestCheckResponse:
    """Test HTTP response error handling."""

    def test_401_raises_auth_error(self, github_service):
        from unittest.mock import MagicMock

        import httpx

        from app.services.github_service import GitHubAuthError

        mock_resp = MagicMock(spec=httpx.Response)
        mock_resp.status_code = 401
        mock_resp.text = "Bad credentials"

        with pytest.raises(GitHubAuthError):
            github_service._check_response(mock_resp)

    def test_200_passes(self, github_service):
        from unittest.mock import MagicMock

        import httpx

        mock_resp = MagicMock(spec=httpx.Response)
        mock_resp.status_code = 200

        # Should not raise
        github_service._check_response(mock_resp)
