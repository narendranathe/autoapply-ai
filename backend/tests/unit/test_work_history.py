"""
Unit tests for work_history router helpers.
Tests the _extract_contact_info function used in resume import.
"""

import sys
import types

# Stub out heavy dependencies so we can import the router helpers without
# starting the full FastAPI application or loading GPU models.
for mod_name in [
    "app.config",
    "app.models.base",
    "app.models.user",
    "app.models.work_history",
    "app.dependencies",
    "app.services.resume_parser",
    "fastapi",
    "sqlalchemy",
    "sqlalchemy.ext.asyncio",
    "loguru",
]:
    if mod_name not in sys.modules:
        stub = types.ModuleType(mod_name)
        sys.modules[mod_name] = stub

# Provide the minimal stubs needed
import app.config as _cfg  # noqa: E402

_cfg.settings = types.SimpleNamespace(  # type: ignore[attr-defined]
    ENVIRONMENT="test", is_development=False
)

import app.models.work_history as _wh  # noqa: E402

_wh.WorkHistoryEntry = object  # type: ignore[attr-defined]

import app.dependencies as _deps  # noqa: E402

_deps.get_db = None  # type: ignore[attr-defined]
_deps.get_current_user = None  # type: ignore[attr-defined]

import app.services.resume_parser as _rp  # noqa: E402

_rp.ResumeParser = object  # type: ignore[attr-defined]

# Import the function under test
from app.routers.work_history import _extract_contact_info  # noqa: E402


class TestExtractContactInfo:
    def test_email_extraction(self):
        text = "John Doe\njohn.doe@example.com\n+1 (555) 123-4567"
        result = _extract_contact_info(text)
        assert result["email"] == "john.doe@example.com"

    def test_email_with_plus(self):
        text = "jane+filter@gmail.com"
        result = _extract_contact_info(text)
        assert result["email"] == "jane+filter@gmail.com"

    def test_phone_formats(self):
        cases = [
            ("Call me at 555-123-4567", "5551234567"),
            ("Phone: (555) 123-4567", "5551234567"),
            ("+1 555 123 4567", "+15551234567"),
        ]
        for text, expected in cases:
            result = _extract_contact_info(text)
            assert result.get("phone") == expected, f"Failed for: {text!r}"

    def test_linkedin_url(self):
        text = "Connect: linkedin.com/in/johndoe\nSome other text"
        result = _extract_contact_info(text)
        assert result["linkedinUrl"] == "https://linkedin.com/in/johndoe"

    def test_github_url(self):
        text = "Code: github.com/johndoe123"
        result = _extract_contact_info(text)
        assert result["githubUrl"] == "https://github.com/johndoe123"

    def test_portfolio_url(self):
        text = "Portfolio: https://johndoe.dev/projects"
        result = _extract_contact_info(text)
        assert result["portfolioUrl"] == "https://johndoe.dev/projects"

    def test_portfolio_excludes_linkedin(self):
        text = "https://linkedin.com/in/jane"
        result = _extract_contact_info(text)
        assert "portfolioUrl" not in result

    def test_portfolio_excludes_github(self):
        text = "https://github.com/jane"
        result = _extract_contact_info(text)
        assert "portfolioUrl" not in result

    def test_name_extraction_two_words(self):
        text = "John Smith\njohnsmith@example.com"
        result = _extract_contact_info(text)
        assert result["firstName"] == "John"
        assert result["lastName"] == "Smith"

    def test_name_extraction_three_words(self):
        text = "Mary Jane Watson\nmary@example.com"
        result = _extract_contact_info(text)
        assert result["firstName"] == "Mary"
        assert result["lastName"] == "Watson"

    def test_name_skips_email_line(self):
        # Email line should be skipped; name should come from next eligible line
        text = "john@example.com\nJohn Smith"
        result = _extract_contact_info(text)
        assert result.get("firstName") == "John"

    def test_name_skips_lines_with_digits(self):
        text = "123 Main Street\nAlice Brown"
        result = _extract_contact_info(text)
        assert result.get("firstName") == "Alice"

    def test_empty_text(self):
        result = _extract_contact_info("")
        assert result == {}

    def test_no_matches(self):
        result = _extract_contact_info("Lorem ipsum dolor sit amet consectetur")
        assert result == {}

    def test_full_resume_header(self):
        text = """Narendra Nath
narendranath9@rocketmail.com | +1 (314) 555-0123
linkedin.com/in/narendranath | github.com/narendranathe
https://narendranath.dev
"""
        result = _extract_contact_info(text)
        assert result["firstName"] == "Narendra"
        assert result["lastName"] == "Nath"
        assert "narendranath9@rocketmail.com" in result["email"]
        assert "linkedin.com/in/narendranath" in result["linkedinUrl"]
        assert "github.com/narendranathe" in result["githubUrl"]
        assert "narendranath.dev" in result["portfolioUrl"]
