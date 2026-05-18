"""
Billing tier limits for Stripe subscription enforcement.

None means unlimited. Enforced at the service layer via get_limit().
"""

FREE_LIMITS: dict[str, int | None] = {
    "resume_tailors": 5,
    "qa_drafts": 20,
    "cover_letters": 3,
}

PRO_LIMITS: dict[str, int | None] = {
    "resume_tailors": None,
    "qa_drafts": None,
    "cover_letters": None,
}

TEAM_LIMITS: dict[str, int | None] = {
    "resume_tailors": None,
    "qa_drafts": None,
    "cover_letters": None,
}

PLAN_LIMITS = {
    "free": FREE_LIMITS,
    "pro": PRO_LIMITS,
    "team": TEAM_LIMITS,
}


def get_limit(plan: str, feature: str) -> int | None:
    """Return the limit for a feature under a given plan. None = unlimited."""
    return PLAN_LIMITS.get(plan, FREE_LIMITS).get(feature)
