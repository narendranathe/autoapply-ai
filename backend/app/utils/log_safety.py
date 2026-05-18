"""Log-line sanitization helpers (Issue #197 P2 round-3/round-4).

Anywhere a user-controlled value (``User-Agent`` header, ``provider_name``
form field, etc.) is interpolated into a structured log line, a
malicious client can inject CRLF to forge a second, attacker-shaped log
line ("log forging" — CWE-117). We defuse that class of bug by escaping
``\\r`` / ``\\n`` to literal two-character sequences and capping the
result at 200 characters so a pathological 64KB header cannot blow up
the log pipeline either.

Use :func:`sanitize_log_value` at every interpolation site whose source
crosses the trust boundary.
"""

from __future__ import annotations

from typing import Any

_MAX_LOG_VALUE_LEN = 200


def sanitize_log_value(v: Any) -> str:
    """Escape CRLF and cap length on a value before logging.

    Accepts any type — ``None`` becomes ``""`` and non-string values are
    coerced via ``str()`` first. Returns the sanitized string ready for
    interpolation.
    """
    if v is None:
        return ""
    if not isinstance(v, str):
        v = str(v)
    if not v:
        return ""
    return v.replace("\r", "\\r").replace("\n", "\\n")[:_MAX_LOG_VALUE_LEN]
