"""Tests for JWKS kid rotation handling — Issue #102."""

from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException
from jose import jwt
from jose.utils import long_to_base64

from app import dependencies


def _rsa_keypair() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _jwk_from_private(key: rsa.RSAPrivateKey, kid: str) -> dict:
    nums = key.public_key().public_numbers()
    return {
        "kty": "RSA",
        "kid": kid,
        "use": "sig",
        "alg": "RS256",
        "n": long_to_base64(nums.n).decode("ascii"),
        "e": long_to_base64(nums.e).decode("ascii"),
    }


def _sign_token(key: rsa.RSAPrivateKey, kid: str, sub: str = "user_abc") -> str:
    payload = {"sub": sub, "iat": int(time.time()), "exp": int(time.time()) + 300}
    return jwt.encode(payload, key, algorithm="RS256", headers={"kid": kid})


def _ensure_dependencies_intact() -> None:
    import sys

    polluted = (
        getattr(dependencies, "get_current_user", None) is None
        or getattr(dependencies, "get_db", None) is None
        or not hasattr(getattr(dependencies, "settings", None), "CLERK_FRONTEND_API_URL")
        or not hasattr(sys.modules.get("app.models.base"), "async_session_factory")
    )
    if not polluted:
        return
    for mod in ("app.dependencies", "app.config", "app.models.base"):
        sys.modules.pop(mod, None)
    import importlib

    import app.config as fresh_config
    import app.models.base as fresh_base

    importlib.reload(fresh_config)
    importlib.reload(fresh_base)

    import app.dependencies as fresh

    fresh = importlib.reload(fresh)
    sys.modules["app.dependencies"] = fresh
    sys.modules["app.config"] = fresh_config
    sys.modules["app.models.base"] = fresh_base
    globals()["dependencies"] = fresh


@pytest.fixture(autouse=True)
def _clear_jwks_cache():
    _ensure_dependencies_intact()
    dependencies._jwks_cache.clear()
    dependencies._jwks_unknown_kids.clear()
    yield
    dependencies._jwks_cache.clear()
    dependencies._jwks_unknown_kids.clear()


# ---------------------------------------------------------------------------
# Cache TTL is set to 900 seconds
# ---------------------------------------------------------------------------
def test_jwks_cache_ttl_is_900_seconds():
    assert dependencies._JWKS_TTL == 900


# ---------------------------------------------------------------------------
# Unknown kid → refresh attempted → still missing → returns None
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_unknown_kid_triggers_single_refresh_then_returns_none():
    keys = [_jwk_from_private(_rsa_keypair(), "kid-current")]
    fetch_mock = AsyncMock(return_value=keys)

    with patch.object(dependencies, "_fetch_clerk_jwks", fetch_mock):
        result = await dependencies._resolve_jwk_for_kid("kid-unknown")

    assert result is None
    assert fetch_mock.await_count == 2


# ---------------------------------------------------------------------------
# Rotated kid: stale cache → force refresh → key found
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_rotated_kid_resolves_after_refresh():
    old_jwk = _jwk_from_private(_rsa_keypair(), "kid-old")
    new_jwk = _jwk_from_private(_rsa_keypair(), "kid-new")

    dependencies._jwks_cache["keys"] = [old_jwk]
    dependencies._jwks_cache["fetched_at"] = time.monotonic()

    refreshed = {"keys": [old_jwk, new_jwk], "fetched_at": time.monotonic()}

    async def fake_fetch() -> list[dict]:
        dependencies._jwks_cache["keys"] = refreshed["keys"]
        dependencies._jwks_cache["fetched_at"] = time.monotonic()
        return refreshed["keys"]

    with patch.object(dependencies, "_fetch_clerk_jwks", side_effect=fake_fetch) as fetch_mock:
        result = await dependencies._resolve_jwk_for_kid("kid-new")

    assert result is not None
    assert result["kid"] == "kid-new"
    assert fetch_mock.await_count == 1


# ---------------------------------------------------------------------------
# Known kid in fresh cache → no refresh needed
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_known_kid_in_cache_skips_refresh():
    jwk = _jwk_from_private(_rsa_keypair(), "kid-current")
    dependencies._jwks_cache["keys"] = [jwk]
    dependencies._jwks_cache["fetched_at"] = time.monotonic()

    fetch_mock = AsyncMock(return_value=[jwk])
    with patch.object(dependencies, "_fetch_clerk_jwks", fetch_mock):
        result = await dependencies._resolve_jwk_for_kid("kid-current")

    assert result is not None
    assert result["kid"] == "kid-current"
    assert fetch_mock.await_count == 0


# ---------------------------------------------------------------------------
# Cache miss after TTL expiry → refresh, find key, no force-refresh
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_expired_cache_triggers_natural_refresh():
    jwk = _jwk_from_private(_rsa_keypair(), "kid-current")
    dependencies._jwks_cache["keys"] = [jwk]
    dependencies._jwks_cache["fetched_at"] = time.monotonic() - dependencies._JWKS_TTL - 10

    fetch_mock = AsyncMock(return_value=[jwk])
    with patch.object(dependencies, "_fetch_clerk_jwks", fetch_mock):
        result = await dependencies._resolve_jwk_for_kid("kid-current")

    assert result is not None
    assert fetch_mock.await_count == 1


# ---------------------------------------------------------------------------
# End-to-end: JWT with unknown kid is rejected with 401 via get_current_user
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_get_current_user_rejects_unknown_kid_with_401():
    server_key = _rsa_keypair()
    server_jwk = _jwk_from_private(server_key, "kid-server")
    attacker_key = _rsa_keypair()
    token = _sign_token(attacker_key, "kid-attacker")

    fetch_mock = AsyncMock(return_value=[server_jwk])

    from starlette.datastructures import Headers
    from starlette.requests import Request

    scope = {
        "type": "http",
        "method": "GET",
        "headers": Headers({"Authorization": f"Bearer {token}"}).raw,
    }
    request = Request(scope)

    with (
        patch.object(dependencies, "_fetch_clerk_jwks", fetch_mock),
        patch.object(dependencies.settings, "CLERK_FRONTEND_API_URL", "https://test.clerk.dev"),
        pytest.raises(HTTPException) as exc_info,
    ):
        await dependencies.get_current_user(
            request=request,
            db=AsyncMock(),
            x_clerk_user_id=None,
        )

    assert exc_info.value.status_code == 401
    assert fetch_mock.await_count == 2


# ---------------------------------------------------------------------------
# End-to-end: JWT signed with rotated kid passes after refresh
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_get_current_user_accepts_rotated_kid_after_refresh(db_session, test_user):
    old_key = _rsa_keypair()
    new_key = _rsa_keypair()
    old_jwk = _jwk_from_private(old_key, "kid-old")
    new_jwk = _jwk_from_private(new_key, "kid-new")

    dependencies._jwks_cache["keys"] = [old_jwk]
    dependencies._jwks_cache["fetched_at"] = time.monotonic()

    fetch_mock = AsyncMock(return_value=[old_jwk, new_jwk])

    token = _sign_token(new_key, "kid-new", sub=test_user.clerk_id)

    from starlette.datastructures import Headers
    from starlette.requests import Request

    scope = {
        "type": "http",
        "method": "GET",
        "headers": Headers({"Authorization": f"Bearer {token}"}).raw,
    }
    request = Request(scope)

    with (
        patch.object(dependencies, "_fetch_clerk_jwks", fetch_mock),
        patch.object(dependencies.settings, "CLERK_FRONTEND_API_URL", "https://test.clerk.dev"),
        patch.object(dependencies.settings, "CLERK_JWT_AUDIENCE", ""),
    ):
        user = await dependencies.get_current_user(
            request=request,
            db=db_session,
            x_clerk_user_id=None,
        )

    assert user.clerk_id == test_user.clerk_id
    assert fetch_mock.await_count == 1


# ---------------------------------------------------------------------------
# JWT missing kid header → 401
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_get_current_user_rejects_token_without_kid():
    key = _rsa_keypair()
    payload = {"sub": "user_x", "iat": int(time.time()), "exp": int(time.time()) + 300}
    token = jwt.encode(payload, key, algorithm="RS256")  # no kid in headers

    from starlette.datastructures import Headers
    from starlette.requests import Request

    scope = {
        "type": "http",
        "method": "GET",
        "headers": Headers({"Authorization": f"Bearer {token}"}).raw,
    }
    request = Request(scope)

    with (
        patch.object(dependencies.settings, "CLERK_FRONTEND_API_URL", "https://test.clerk.dev"),
        pytest.raises(HTTPException) as exc_info,
    ):
        await dependencies.get_current_user(
            request=request,
            db=AsyncMock(),
            x_clerk_user_id=None,
        )

    assert exc_info.value.status_code == 401


# ---------------------------------------------------------------------------
# Negative cache: repeated unknown-kid requests within TTL skip the upstream
# fetch entirely (DoS amplification mitigation).
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_unknown_kid_uses_negative_cache_on_repeat():
    keys = [_jwk_from_private(_rsa_keypair(), "kid-current")]
    fetch_mock = AsyncMock(return_value=keys)

    with patch.object(dependencies, "_fetch_clerk_jwks", fetch_mock):
        first = await dependencies._resolve_jwk_for_kid("kid-bogus")
        # First request: initial fetch + force-refresh = 2 upstream calls.
        assert first is None
        assert fetch_mock.await_count == 2
        assert "kid-bogus" in dependencies._jwks_unknown_kids

        second = await dependencies._resolve_jwk_for_kid("kid-bogus")
        # Second request within TTL: zero additional upstream calls.
        assert second is None
        assert fetch_mock.await_count == 2


# ---------------------------------------------------------------------------
# Graceful degradation: Clerk outage with a populated cache serves stale keys.
# Stale cache contains the requested kid, but TTL has expired so the natural
# fetch fires and raises — we fall back to the cached keys and resolve the kid.
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_clerk_jwks_outage_with_cache_serves_stale():
    jwk = _jwk_from_private(_rsa_keypair(), "kid-stale")
    dependencies._jwks_cache["keys"] = [jwk]
    # Force TTL expiry so _get_clerk_jwks() actually calls _fetch_clerk_jwks().
    dependencies._jwks_cache["fetched_at"] = time.monotonic() - dependencies._JWKS_TTL - 10

    async def boom() -> list[dict]:
        raise httpx.ConnectError("clerk down")

    with patch.object(dependencies, "_fetch_clerk_jwks", side_effect=boom):
        result = await dependencies._resolve_jwk_for_kid("kid-stale")

    # Stale cache had kid-stale → returned via fallback after the failed refresh.
    assert result is not None
    assert result["kid"] == "kid-stale"


# ---------------------------------------------------------------------------
# Clerk outage with no cache at all → 503 (not a leaked 500).
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_clerk_jwks_outage_without_cache_raises_503():
    async def boom() -> list[dict]:
        raise httpx.ConnectError("clerk down")

    with (
        patch.object(dependencies, "_fetch_clerk_jwks", side_effect=boom),
        pytest.raises(HTTPException) as exc_info,
    ):
        await dependencies._resolve_jwk_for_kid("kid-anything")

    assert exc_info.value.status_code == 503


# ---------------------------------------------------------------------------
# Thundering-herd guard: concurrent unknown-kid requests coalesce into a
# single force-refresh upstream call.
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_concurrent_refreshes_coalesce():
    jwk = _jwk_from_private(_rsa_keypair(), "kid-current")
    # Pre-populate a fresh cache so only the force-refresh path can fetch.
    dependencies._jwks_cache["keys"] = [jwk]
    dependencies._jwks_cache["fetched_at"] = time.monotonic()

    call_count = 0
    refresh_started = asyncio.Event()
    release_refresh = asyncio.Event()

    async def slow_fetch() -> list[dict]:
        nonlocal call_count
        call_count += 1
        refresh_started.set()
        # Hold the lock long enough for the second coroutine to queue up.
        await release_refresh.wait()
        return [jwk]

    async def driver(kid: str) -> dict | None:
        return await dependencies._resolve_jwk_for_kid(kid)

    with patch.object(dependencies, "_fetch_clerk_jwks", side_effect=slow_fetch):
        task_a = asyncio.create_task(driver("kid-missing"))
        # Wait until the first task is inside the locked force-refresh.
        await refresh_started.wait()
        task_b = asyncio.create_task(driver("kid-missing"))
        # Yield so task_b can attempt to acquire the lock and queue.
        await asyncio.sleep(0)
        release_refresh.set()
        results = await asyncio.gather(task_a, task_b)

    # Only one upstream force-refresh fired despite two concurrent callers.
    assert call_count == 1
    assert results == [None, None]


# ---------------------------------------------------------------------------
# A kid that was negatively cached must be unblocked the moment Clerk
# publishes it; otherwise legitimate users stay 401'd for the TTL window.
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_negative_cache_invalidated_on_successful_refresh():
    # Pre-populate the negative cache with a recent miss for kid-X.
    dependencies._jwks_unknown_kids["kid-X"] = time.monotonic()
    assert "kid-X" in dependencies._jwks_unknown_kids

    jwk = _jwk_from_private(_rsa_keypair(), "kid-X")

    async def fake_get(url):  # noqa: ANN001
        class _Resp:
            def raise_for_status(self) -> None:  # pragma: no cover - noop
                return None

            def json(self) -> dict:
                return {"keys": [jwk]}

        return _Resp()

    class _FakeClient:
        def __init__(self, *args, **kwargs) -> None:  # noqa: ANN002, ANN003
            pass

        async def __aenter__(self) -> _FakeClient:
            return self

        async def __aexit__(self, *exc) -> None:  # noqa: ANN002
            return None

        async def get(self, url):  # noqa: ANN001
            return await fake_get(url)

    with patch.object(dependencies.httpx, "AsyncClient", _FakeClient):
        keys = await dependencies._fetch_clerk_jwks()

    assert any(k["kid"] == "kid-X" for k in keys)
    # The freshly-published kid must be evicted from the negative cache.
    assert "kid-X" not in dependencies._jwks_unknown_kids


# ---------------------------------------------------------------------------
# Negative cache must FIFO-evict to bound memory under random-kid spam.
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_negative_cache_fifo_eviction():
    cap = dependencies._JWKS_UNKNOWN_KIDS_MAX
    # Fill the negative cache to capacity with monotonically increasing ts.
    base = time.monotonic()
    for i in range(cap):
        dependencies._jwks_unknown_kids[f"kid-{i:04d}"] = base + i

    assert len(dependencies._jwks_unknown_kids) == cap
    oldest_key = f"kid-{0:04d}"
    assert oldest_key in dependencies._jwks_unknown_kids

    # Trigger a fresh miss via _resolve_jwk_for_kid; only kid "kid-current"
    # exists upstream, so "kid-new" will be recorded as a negative-cache entry.
    keys = [_jwk_from_private(_rsa_keypair(), "kid-current")]
    fetch_mock = AsyncMock(return_value=keys)

    with patch.object(dependencies, "_fetch_clerk_jwks", fetch_mock):
        result = await dependencies._resolve_jwk_for_kid("kid-new")

    assert result is None
    # Cap is preserved.
    assert len(dependencies._jwks_unknown_kids) == cap
    # New kid is in.
    assert "kid-new" in dependencies._jwks_unknown_kids
    # Oldest kid was evicted.
    assert oldest_key not in dependencies._jwks_unknown_kids
