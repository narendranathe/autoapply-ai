"""
Unit tests for the rate limiter middleware.
Focuses on client identification and LLM path detection logic.
"""

import sys
import types

# Stub out dependencies
for mod_name in [
    "app.config",
    "loguru",
    "starlette",
    "starlette.middleware",
    "starlette.middleware.base",
    "starlette.requests",
    "starlette.responses",
    "redis",
    "redis.asyncio",
]:
    if mod_name not in sys.modules:
        sys.modules[mod_name] = types.ModuleType(mod_name)

import app.config as _cfg  # noqa: E402

_cfg.settings = types.SimpleNamespace(REDIS_URL="redis://localhost:6379")  # type: ignore


# Patch BaseHTTPMiddleware to be a no-op base class
class _FakeBase:
    def __init__(self, app, **kwargs):
        self.app = app


sys.modules["starlette.middleware.base"].BaseHTTPMiddleware = _FakeBase  # type: ignore

from app.middleware.rate_limit import _LLM_PATHS, _LLM_RPM, RateLimitMiddleware  # noqa: E402


class TestLLMPathDetection:
    def test_answers_is_llm_path(self):
        assert "/api/v1/vault/generate/answers" in _LLM_PATHS

    def test_tailored_is_llm_path(self):
        assert "/api/v1/vault/generate/tailored" in _LLM_PATHS

    def test_interview_prep_is_llm_path(self):
        assert "/api/v1/vault/interview-prep" in _LLM_PATHS

    def test_import_from_resume_is_llm_path(self):
        assert "/api/v1/work-history/import-from-resume" in _LLM_PATHS

    def test_cover_letter_is_llm_path(self):
        assert "/api/v1/vault/generate/cover-letter" in _LLM_PATHS

    def test_trim_answers_is_llm_path(self):
        assert "/api/v1/vault/generate/answers/trim" in _LLM_PATHS

    def test_health_is_not_llm_path(self):
        assert "/health" not in _LLM_PATHS

    def test_applications_list_is_not_llm_path(self):
        assert "/api/v1/applications" not in _LLM_PATHS

    def test_llm_rpm_is_stricter(self):
        """LLM cap must be lower than general API cap."""
        assert _LLM_RPM < 60
        assert _LLM_RPM == 10


class TestRateLimiterInit:
    def test_default_rpm(self):
        mw = RateLimitMiddleware(app=None, requests_per_minute=60)
        assert mw.rpm == 60

    def test_custom_rpm(self):
        mw = RateLimitMiddleware(app=None, requests_per_minute=30)
        assert mw.rpm == 30
