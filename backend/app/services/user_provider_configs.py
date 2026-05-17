r"""
Server-side provider key resolution (Issue #197).

Single resolver function ``resolve_decrypted_key`` looks up a user's stored
provider config row, decrypts the API key in-memory, and returns it wrapped
in a ``DecryptedKey`` value type.

Why the wrapper?
----------------
Defence in depth: if a caller accidentally writes
``logger.info(f"key={key}")`` the plaintext must never reach the log sink.
``DecryptedKey`` overrides both ``__repr__`` and ``__str__`` to emit
``"[REDACTED]"``, and the only way to obtain the raw string is via the
explicit ``.expose()`` method. Callers therefore opt-in to leak risk
exactly at the point where they hand the secret to ``httpx`` / the LLM
gateway, and grep can audit every ``.expose()`` site.

Contract
--------
* ``resolve_decrypted_key(user_id, provider_name, db)`` returns
  ``DecryptedKey | None``. ``None`` means: no row, empty stored key, or
  decryption failed. Callers MUST treat ``None`` as "this provider is not
  configured server-side".
* ``DecryptedKey(...)`` is immutable; reuse a single instance per call.
* ``DecryptedKey.expose()`` is the only sanctioned way to read the
  plaintext. It is documented as a leak-risk boundary; auditors should
  ``grep -n "\.expose()"`` to enumerate every site.

Issue #197 — extension/client no longer transmits provider API keys on
every generation request. The client sends ``{name, model}`` only and the
backend resolves the key from ``user_provider_configs`` via this module.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING

from loguru import logger
from sqlalchemy import select

from app.models.user_provider_config import UserProviderConfig
from app.utils.encryption import decrypt_value

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True)
class DecryptedKey:
    """Opaque wrapper around a decrypted API key.

    The plaintext is held in ``_value`` (private by convention). Both
    ``repr()`` and ``str()`` return ``"[REDACTED]"`` so an accidental
    ``logger.info(f"key={key}")`` cannot leak the secret. Use
    :py:meth:`expose` exactly at the boundary that hands the key to the
    LLM provider HTTP call.
    """

    _value: str

    def __post_init__(self) -> None:
        if not isinstance(self._value, str):  # pragma: no cover - defensive
            raise TypeError("DecryptedKey wraps str only")
        if not self._value:
            raise ValueError("DecryptedKey rejects empty plaintext — use None instead")

    # -- Redaction --

    def __repr__(self) -> str:  # noqa: D401 - documented in class docstring
        return "[REDACTED]"

    def __str__(self) -> str:  # noqa: D401 - documented in class docstring
        return "[REDACTED]"

    def __format__(self, format_spec: str) -> str:
        # f"{key}" → "[REDACTED]" regardless of format spec.
        return "[REDACTED]"

    # -- Sanctioned escape hatch --

    def expose(self) -> str:
        """Return the plaintext API key.

        SECURITY: every call site of ``.expose()`` is a leak-risk boundary.
        Only call this at the HTTP boundary that hands the key to the LLM
        provider. Never log or interpolate the return value.
        """
        return self._value


async def resolve_decrypted_key(
    user_id: uuid.UUID,
    provider_name: str,
    db: AsyncSession,
) -> DecryptedKey | None:
    """Look up + decrypt the user's stored key for ``provider_name``.

    Returns ``None`` when:
    * no row exists for ``(user_id, provider_name)``
    * the row exists but ``encrypted_api_key`` is empty
    * decryption raises (corrupted ciphertext or Fernet key mismatch)

    Callers MUST treat ``None`` as "this provider is not configured" and
    skip the provider entirely.
    """
    stmt = select(UserProviderConfig).where(
        UserProviderConfig.user_id == user_id,
        UserProviderConfig.provider_name == provider_name,
    )
    result = await db.execute(stmt)
    row = result.scalar_one_or_none()
    if row is None or not row.encrypted_api_key:
        return None
    try:
        plaintext = decrypt_value(row.encrypted_api_key)
    except Exception:
        # decrypt_value already logged the failure (without echoing the
        # ciphertext). Treat decryption failure as "no key" so the caller
        # falls through to other providers / keyword fallback.
        logger.warning(
            "resolve_decrypted_key: decrypt failed for user={} provider={}",
            user_id,
            provider_name,
        )
        return None
    if not plaintext:
        return None
    return DecryptedKey(plaintext)


async def resolve_user_providers(
    user_id: uuid.UUID,
    requested: list[dict],
    db: AsyncSession,
) -> list[dict]:
    """Resolve client-supplied ``[{name, model}, ...]`` into provider dicts
    enriched with decrypted API keys (still wrapped in ``DecryptedKey``).

    Output schema::

        [
            {"name": "anthropic", "model": "claude-...", "api_key": DecryptedKey},
            ...
        ]

    Providers without a server-side key are silently dropped. Ollama is a
    special case — it needs no API key, so it passes through with
    ``api_key=None``.

    Callers should call ``entry["api_key"].expose()`` exactly when
    handing the key to the LLM provider HTTP call.
    """
    enriched: list[dict] = []
    for entry in requested:
        name = (entry.get("name") or "").strip()
        model = (entry.get("model") or "").strip()
        if not name:
            continue
        if name == "ollama":
            enriched.append({"name": name, "model": model, "api_key": None})
            continue
        key = await resolve_decrypted_key(user_id, name, db)
        if key is None:
            logger.debug(
                "resolve_user_providers: no server-side key for user={} provider={} — skipping",
                user_id,
                name,
            )
            continue
        enriched.append({"name": name, "model": model, "api_key": key})
    return enriched
