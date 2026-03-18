"""
Reflection API endpoint.

POST /api/v1/reflect — SSE stream of Claude-powered career reflection.

The endpoint:
1. Validates auth and fetches required DB data (application context, provider config).
2. Builds system + user prompts from that data.
3. Returns a StreamingResponse that streams LLM output word by word as SSE.
4. Writes an AuditLog row after the stream finishes.

All DB work happens before the generator runs to avoid holding a connection
open during the entire LLM call.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import AsyncGenerator

from fastapi import APIRouter, Body, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user, get_db
from app.models.application import Application
from app.models.audit_log import AuditLog
from app.models.user import User
from app.models.user_provider_config import UserProviderConfig
from app.schemas.reflect import ReflectRequest
from app.services.llm_gateway import LLMGateway
from app.utils.encryption import decrypt_value

router = APIRouter()
_gateway = LLMGateway()

_SYSTEM_PROMPT = (
    "You are a career coach and recruiter with 15 years of experience. "
    "Analyze the candidate's profile and provide a structured reflection "
    "with four sections: Recruiter First Impression, Skill Gap Analysis, "
    "Top 3 Improvements, and Confidence Score (0-100). "
    "Be direct, human, and specific. No emojis."
)


@router.post("/reflect")
async def stream_reflection(
    body: ReflectRequest = Body(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> StreamingResponse:
    """
    Stream a structured career reflection as Server-Sent Events.

    Returns Content-Type: text/event-stream.
    Each SSE frame is: ``data: <token>\\n\\n``
    On LLM error: ``event: error\\ndata: <message>\\n\\n``
    """
    start_ms = int(time.monotonic() * 1000)
    request_id = str(uuid.uuid4())

    # ── 1. Fetch application context (if requested) ───────────────────────
    application_context = ""
    if body.context_type == "application":
        if not body.application_id:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="application_id is required when context_type is 'application'.",
            )
        result = await db.execute(
            select(Application).where(
                Application.id == uuid.UUID(body.application_id),
                Application.user_id == user.id,
            )
        )
        app = result.scalar_one_or_none()
        if not app:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Application not found.",
            )
        application_context = f"Company: {app.company_name}\nRole: {app.role_title}"

    # ── 2. Fetch best enabled provider config ─────────────────────────────
    provider_result = await db.execute(
        select(UserProviderConfig)
        .where(
            UserProviderConfig.user_id == user.id,
            UserProviderConfig.is_enabled.is_(True),
        )
        .limit(1)
    )
    config = provider_result.scalar_one_or_none()
    provider = config.provider_name if config else "ollama"
    api_key = decrypt_value(config.encrypted_api_key) if config and config.encrypted_api_key else ""

    # ── 3. Build prompts (all DB work done before streaming begins) ───────
    context_parts: list[str] = []
    if application_context:
        context_parts.append(application_context)
    if body.jd_text:
        context_parts.append(f"Job Description:\n{body.jd_text}")
    if body.profile_summary:
        context_parts.append(f"Profile:\n{body.profile_summary}")
    user_prompt = (
        "\n\n".join(context_parts) if context_parts else "Analyze my general career profile."
    )

    # ── 4. Generator (runs after this handler returns) ────────────────────
    async def generate() -> AsyncGenerator[str, None]:
        success = True
        error_msg: str | None = None
        try:
            content, _ = await _gateway.generate(
                system_prompt=_SYSTEM_PROMPT,
                user_prompt=user_prompt,
                provider=provider,
                api_key=api_key,
            )
            if content:
                words = content.split(" ")
                for i, word in enumerate(words):
                    token = word if i == 0 else f" {word}"
                    yield f"data: {token}\n\n"
                yield "data: [DONE]\n\n"
            else:
                yield "event: error\ndata: Reflection unavailable. Check your provider configuration in Settings.\n\n"
                success = False
                error_msg = "empty_response"
        except Exception as exc:
            yield "event: error\ndata: Reflection unavailable. Check your provider configuration in Settings.\n\n"
            success = False
            error_msg = str(exc)
        finally:
            duration_ms = int(time.monotonic() * 1000) - start_ms
            log = AuditLog(
                user_hash=str(user.id),
                request_id=request_id,
                action="reflect_stream",
                success=success,
                error_message=error_msg,
                duration_ms=duration_ms,
            )
            db.add(log)
            await db.flush()

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
