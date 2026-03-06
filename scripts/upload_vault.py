"""
Batch upload PDFs from job-scout local vault to the AutoApply AI production API.

Usage:
    python scripts/upload_vault.py

Reads PDFs from job-scout/backend/resume_vault/pdf/ and uploads each one to
https://autoapply-ai-api.fly.dev/api/v1/vault/upload
"""

import os
import sys
import time
from pathlib import Path

import requests

API_BASE = "https://autoapply-ai-api.fly.dev/api/v1"
CLERK_USER_ID = "user_3AB26PAgD82zYApFLsMeqaTQyDT"
VAULT_DIR = Path(__file__).parent.parent.parent / "job-scout" / "backend" / "resume_vault" / "pdf"

# Company and role abbreviation mappings (mirrors resume_vault.py parser)
COMPANY_ALIASES = {
    "gs": "Goldman Sachs", "goldmansachs": "Goldman Sachs",
    "ms": "Morgan Stanley", "morganstanley": "Morgan Stanley",
    "jpm": "JPMorgan", "jpmc": "JPMorgan Chase",
    "meta": "Meta", "fb": "Meta",
    "bofa": "Bank of America", "bofasec": "Bank of America",
    "capitalone": "Capital One", "cap1": "Capital One",
    "sf": "Salesforce", "salesforce": "Salesforce",
    "att": "AT&T",
    "bloomberg": "Bloomberg", "bb": "Bloomberg",
    "anthropic": "Anthropic", "openai": "OpenAI",
    "stripe": "Stripe", "databricks": "Databricks",
    "snowflake": "Snowflake", "netflix": "Netflix",
    "spotify": "Spotify", "discord": "Discord",
    "twosigma": "Two Sigma", "citadel": "Citadel",
    "hrt": "Hudson River Trading", "walmart": "Walmart",
    "google": "Google", "microsoft": "Microsoft",
    "amazon": "Amazon", "apple": "Apple",
    "nvidia": "NVIDIA", "uber": "Uber",
    "fidelity": "Fidelity", "doordash": "DoorDash",
    "grubhub": "Grubhub",
}

ROLE_ALIASES = {
    "de": "Data Engineer", "data": "Data Engineer",
    "ml": "ML Engineer", "ai": "AI Engineer",
    "ae": "Analytics Engineer", "ds": "Data Scientist",
    "sde": "Software Engineer", "se": "Software Engineer",
    "dq": "Data Quality Engineer",
    "quant": "Quant Strategist",
    "platform": "Platform Engineer",
}


def parse_filename(stem: str) -> tuple[str, str, str]:
    """
    Returns (version_tag, company, role) from a filename stem.
    Handles patterns like:
      Narendranath_GS_data  → Goldman Sachs, Data Engineer
      Naren_DE              → unknown company, Data Engineer
      Narendra_Bloomberg    → Bloomberg, unknown role
    """
    # Strip common name prefixes
    for prefix in ("narendranath_edara_", "narendranath_", "narendra_", "naren_"):
        low = stem.lower()
        if low.startswith(prefix):
            stem = stem[len(prefix):]
            break

    parts = [p.lower() for p in stem.split("_") if p]

    company = "General"
    role = "Data Engineer"

    if len(parts) >= 2:
        c_key = parts[0]
        r_key = "_".join(parts[1:])
        company = COMPANY_ALIASES.get(c_key, c_key.capitalize())
        role = ROLE_ALIASES.get(r_key, None) or ROLE_ALIASES.get(parts[1], parts[1].capitalize())
    elif len(parts) == 1:
        key = parts[0]
        if key in COMPANY_ALIASES:
            company = COMPANY_ALIASES[key]
        elif key in ROLE_ALIASES:
            role = ROLE_ALIASES[key]
        else:
            company = key.capitalize()

    version_tag = stem.replace(" ", "_")
    return version_tag, company, role


def upload(pdf_path: Path, session: requests.Session) -> dict:
    stem = pdf_path.stem
    version_tag, company, role = parse_filename(stem)

    with open(pdf_path, "rb") as f:
        resp = session.post(
            f"{API_BASE}/vault/upload",
            headers={"X-Clerk-User-Id": CLERK_USER_ID},
            files={"file": (pdf_path.name, f, "application/pdf")},
            data={
                "version_tag": version_tag,
                "target_company": company,
                "target_role": role,
            },
            timeout=30,
        )

    return {"file": pdf_path.name, "status": resp.status_code, "ok": resp.ok,
            "company": company, "role": role, "detail": resp.text[:120] if not resp.ok else ""}


def main():
    if not VAULT_DIR.exists():
        print(f"ERROR: vault dir not found: {VAULT_DIR}")
        sys.exit(1)

    pdfs = sorted(VAULT_DIR.glob("*.pdf"))
    print(f"Found {len(pdfs)} PDFs in {VAULT_DIR}\n")

    session = requests.Session()

    # Health check first
    try:
        hc = session.get(f"{API_BASE.replace('/api/v1', '')}/health", timeout=10)
        print(f"API health: {hc.json()}\n")
    except Exception as e:
        print(f"WARNING: health check failed — {e}")

    ok_count = 0
    fail_count = 0
    skip_count = 0

    for i, pdf in enumerate(pdfs, 1):
        result = upload(pdf, session)
        status_sym = "OK" if result["ok"] else ("SKIP" if result["status"] == 409 else "FAIL")

        if result["status"] == 409:
            skip_count += 1
        elif result["ok"]:
            ok_count += 1
        else:
            fail_count += 1

        print(f"[{i:3}/{len(pdfs)}] {status_sym}  {pdf.name[:45]:<45}  {result['company'][:20]:<20}  {result['role']}")
        if result["detail"]:
            print(f"         ERR: {result['detail']}")

        # Avoid hammering the API — small delay between uploads
        time.sleep(0.3)

    print(f"\n{'='*60}")
    print(f"  Uploaded : {ok_count}")
    print(f"  Skipped  : {skip_count}  (already in vault)")
    print(f"  Failed   : {fail_count}")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
