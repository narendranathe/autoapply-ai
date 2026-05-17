"""
Health check endpoints — the MOST important routes in your API.

/health → Liveness probe. "Is the process running?"
/ready  → Readiness probe. "Can we serve traffic?"
/metrics → Prometheus scrape endpoint
"""

import asyncio

from fastapi import APIRouter, Depends, Response, status
from loguru import logger
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db, get_redis
from app.middleware.circuit_breaker import github_circuit, llm_circuit, pdf_circuit

router = APIRouter()

# Bound dependency probes so a hung pool checkout can't blow Fly's 10s probe budget.
_DEP_CHECK_TIMEOUT_SECONDS = 2.0


@router.get("/health")
async def health(
    response: Response,
    db: AsyncSession = Depends(get_db),  # noqa: B008
    redis=Depends(get_redis),  # noqa: B008
):
    """Liveness probe with DB + Redis validation (Fly.io health check)."""
    db_status = "ok"
    try:
        await asyncio.wait_for(db.execute(text("SELECT 1")), timeout=_DEP_CHECK_TIMEOUT_SECONDS)
    except TimeoutError as e:
        logger.warning(f"/health db check timed out after {_DEP_CHECK_TIMEOUT_SECONDS}s: {e}")
        db_status = "error: TimeoutError"
    except Exception as e:
        logger.warning(f"/health db check failed: {type(e).__name__}: {e}")
        db_status = f"error: {type(e).__name__}"

    redis_status = "ok"
    try:
        pong = await asyncio.wait_for(redis.ping(), timeout=_DEP_CHECK_TIMEOUT_SECONDS)
        if not pong:
            redis_status = "error: no pong"
    except TimeoutError as e:
        logger.warning(f"/health redis check timed out after {_DEP_CHECK_TIMEOUT_SECONDS}s: {e}")
        redis_status = "error: TimeoutError"
    except Exception as e:
        logger.warning(f"/health redis check failed: {type(e).__name__}: {e}")
        redis_status = f"error: {type(e).__name__}"

    healthy = db_status == "ok" and redis_status == "ok"
    if not healthy:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"status": "degraded", "db": db_status, "redis": redis_status}
    return {"status": "ok", "db": db_status, "redis": redis_status}


@router.get("/ready")
async def ready(
    db: AsyncSession = Depends(get_db),  # noqa: B008
    redis=Depends(get_redis),  # noqa: B008
):
    """Readiness probe."""
    checks: dict[str, str] = {}

    # PostgreSQL
    try:
        await asyncio.wait_for(db.execute(text("SELECT 1")), timeout=_DEP_CHECK_TIMEOUT_SECONDS)
        checks["database"] = "ok"
    except TimeoutError as e:
        logger.warning(f"/ready db check timed out after {_DEP_CHECK_TIMEOUT_SECONDS}s: {e}")
        checks["database"] = "error: TimeoutError"
    except Exception as e:
        logger.warning(f"/ready db check failed: {type(e).__name__}: {e}")
        checks["database"] = f"error: {type(e).__name__}"

    # Redis
    try:
        pong = await asyncio.wait_for(redis.ping(), timeout=_DEP_CHECK_TIMEOUT_SECONDS)
        checks["redis"] = "ok" if pong else "error: no pong"
    except TimeoutError as e:
        logger.warning(f"/ready redis check timed out after {_DEP_CHECK_TIMEOUT_SECONDS}s: {e}")
        checks["redis"] = "error: TimeoutError"
    except Exception as e:
        logger.warning(f"/ready redis check failed: {type(e).__name__}: {e}")
        checks["redis"] = f"error: {type(e).__name__}"

    # Circuit Breakers
    checks["circuit_github"] = github_circuit.state.value
    checks["circuit_llm"] = llm_circuit.state.value
    checks["circuit_pdf"] = pdf_circuit.state.value

    # Overall verdict
    critical = {k: v for k, v in checks.items() if k in {"database", "redis"}}
    all_ok = all(v == "ok" for v in critical.values())

    return {
        "status": "ready" if all_ok else "degraded",
        "checks": checks,
    }


@router.get("/debug/circuits")
async def circuit_status():
    """Show circuit breaker states for debugging."""
    return {
        "circuits": [
            github_circuit.get_metrics(),
            llm_circuit.get_metrics(),
            pdf_circuit.get_metrics(),
        ]
    }
