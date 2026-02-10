"""
Health check endpoints — the MOST important routes in your API.

/health → Liveness probe. "Is the process running?"
/ready  → Readiness probe. "Can we serve traffic?"
/metrics → Prometheus scrape endpoint
"""

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db, get_redis
from app.middleware.circuit_breaker import github_circuit, llm_circuit, pdf_circuit

router = APIRouter()


@router.get("/health")
async def health():
    """Liveness probe."""
    return {"status": "alive", "service": "autoapply-ai"}


@router.get("/ready")
async def ready(
    db: AsyncSession = Depends(get_db),  # noqa: B008
    redis=Depends(get_redis),  # noqa: B008
):
    """Readiness probe."""
    checks: dict[str, str] = {}

    # PostgreSQL
    try:
        await db.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as e:
        checks["database"] = f"error: {type(e).__name__}"

    # Redis
    try:
        pong = await redis.ping()
        checks["redis"] = "ok" if pong else "error: no pong"
    except Exception as e:
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
