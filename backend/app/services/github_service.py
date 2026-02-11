"""
GitHub Service — Resume version control using user's own repositories.

ARCHITECTURE:
Each user gets a private GitHub repo (default: "resume-vault").
Resumes are stored as files in a directory structure:

    resume-vault/
    +-- template/
    |   +-- resume.docx            # Base/master resume
    +-- applications/
    |   +-- google-swe-2025-02-09/
    |   |   +-- resume.docx        # Tailored version
    |   |   +-- resume.pdf         # Compiled PDF
    |   |   +-- metadata.json      # JD hash, similarity, changes
    |   +-- meta-ml-eng-2025-02-10/
    |       +-- resume.docx
    |       +-- metadata.json
    +-- briefings/                  # Future: company research docs

WHY DIRECTORIES, NOT BRANCHES:
Original brief used branches. After 50 applications, you'd have 50 branches
and GitHub's branch picker becomes unusable. Directories scale better,
are easier to browse, and support the same "version per application" model.

RATE LIMITING:
GitHub API allows 5000 requests/hour per authenticated user.
We use circuit breaker + LRU cache to stay well under this limit.
"""
import base64
import json
from datetime import datetime, timezone
from typing import Any

import httpx
from loguru import logger

from app.middleware.circuit_breaker import github_circuit, CircuitOpenError
from app.utils.encryption import decrypt_value


class GitHubError(Exception):
    """Base exception for GitHub operations."""
    pass


class GitHubAuthError(GitHubError):
    """Token is invalid or expired."""
    pass


class GitHubRateLimitError(GitHubError):
    """GitHub API rate limit hit."""
    pass


class GitHubService:
    """
    Manages resume storage in user's GitHub repository.

    All methods require an encrypted GitHub token, which is
    decrypted just before the API call and never stored in memory.
    """

    BASE_URL = "https://api.github.com"
    DEFAULT_REPO_NAME = "resume-vault"

    def _build_headers(self, token: str) -> dict[str, str]:
        """Build authenticated headers for GitHub API."""
        return {
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github.v3+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    def _decrypt_token(self, encrypted_token: str) -> str:
        """Decrypt the user's GitHub token."""
        try:
            return decrypt_value(encrypted_token)
        except Exception as e:
            raise GitHubAuthError(f"Failed to decrypt GitHub token: {e}")

    # ══════════════════════════════════════════════════════
    # REPOSITORY MANAGEMENT
    # ══════════════════════════════════════════════════════

    @github_circuit
    async def get_username(self, encrypted_token: str) -> str:
        """Get the authenticated user's GitHub username."""
        token = self._decrypt_token(encrypted_token)
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                f"{self.BASE_URL}/user",
                headers=self._build_headers(token),
            )
            self._check_response(resp)
            return resp.json()["login"]

    @github_circuit
    async def ensure_repo_exists(
        self,
        encrypted_token: str,
        repo_name: str = DEFAULT_REPO_NAME,
    ) -> dict[str, str]:
        """
        Create the resume repo if it doesn't exist.

        Returns:
            {"full_name": "username/resume-vault", "created": True/False}
        """
        token = self._decrypt_token(encrypted_token)
        headers = self._build_headers(token)

        async with httpx.AsyncClient(timeout=15.0) as client:
            # Get username
            user_resp = await client.get(f"{self.BASE_URL}/user", headers=headers)
            self._check_response(user_resp)
            username = user_resp.json()["login"]
            full_name = f"{username}/{repo_name}"

            # Check if repo exists
            repo_resp = await client.get(
                f"{self.BASE_URL}/repos/{full_name}",
                headers=headers,
            )

            if repo_resp.status_code == 200:
                logger.info(f"Repo already exists: {full_name}")
                return {"full_name": full_name, "created": False}

            # Create private repo
            create_resp = await client.post(
                f"{self.BASE_URL}/user/repos",
                headers=headers,
                json={
                    "name": repo_name,
                    "private": True,
                    "description": "Resume version control powered by AutoApply AI",
                    "auto_init": True,  # Creates initial commit with README
                    "gitignore_template": None,
                },
            )
            self._check_response(create_resp)
            logger.info(f"Created new repo: {full_name}")

            return {"full_name": full_name, "created": True}

    # ══════════════════════════════════════════════════════
    # FILE OPERATIONS
    # ══════════════════════════════════════════════════════

    @github_circuit
    async def upload_base_template(
        self,
        encrypted_token: str,
        repo_full_name: str,
        file_content: bytes,
        filename: str = "resume.docx",
    ) -> str:
        """
        Upload/update the base resume template.

        Stored at: template/{filename}
        Returns: Git commit SHA
        """
        path = f"template/{filename}"
        sha = await self._commit_file(
            encrypted_token=encrypted_token,
            repo_full_name=repo_full_name,
            file_path=path,
            content=file_content,
            commit_message=f"Update base resume template: {filename}",
        )
        logger.info(f"Uploaded base template to {repo_full_name}/{path}")
        return sha

    @github_circuit
    async def commit_tailored_resume(
        self,
        encrypted_token: str,
        repo_full_name: str,
        company: str,
        role: str,
        resume_content: bytes,
        resume_filename: str,
        metadata: dict[str, Any],
        pdf_content: bytes | None = None,
    ) -> dict[str, str]:
        """
        Commit a tailored resume for a specific application.

        Creates directory: applications/{company}-{role}-{date}/
        Commits: resume file + metadata.json + optional PDF

        Args:
            encrypted_token: Encrypted GitHub PAT
            repo_full_name: "username/resume-vault"
            company: Company name
            role: Role title
            resume_content: The tailored resume file bytes
            resume_filename: Original filename (e.g., "resume.docx")
            metadata: Application metadata (JD hash, changes, etc.)
            pdf_content: Optional compiled PDF bytes

        Returns:
            {"dir_path": "applications/...", "resume_sha": "...", "metadata_sha": "..."}
        """
        # Build safe directory name
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        safe_company = self._sanitize_path(company)[:30]
        safe_role = self._sanitize_path(role)[:30]
        dir_path = f"applications/{safe_company}-{safe_role}-{date_str}"

        # Add timestamp and dir_path to metadata
        metadata["committed_at"] = datetime.now(timezone.utc).isoformat()
        metadata["dir_path"] = dir_path
        metadata["company"] = company
        metadata["role"] = role

        # Commit resume file
        ext = resume_filename.rsplit(".", 1)[-1] if "." in resume_filename else "docx"
        resume_path = f"{dir_path}/resume.{ext}"
        resume_sha = await self._commit_file(
            encrypted_token=encrypted_token,
            repo_full_name=repo_full_name,
            file_path=resume_path,
            content=resume_content,
            commit_message=f"Add tailored resume for {company} - {role}",
        )

        # Commit metadata
        metadata_path = f"{dir_path}/metadata.json"
        metadata_bytes = json.dumps(metadata, indent=2, default=str).encode("utf-8")
        metadata_sha = await self._commit_file(
            encrypted_token=encrypted_token,
            repo_full_name=repo_full_name,
            file_path=metadata_path,
            content=metadata_bytes,
            commit_message=f"Add metadata for {company} - {role}",
        )

        # Commit PDF if provided
        pdf_sha = None
        if pdf_content:
            pdf_path = f"{dir_path}/resume.pdf"
            pdf_sha = await self._commit_file(
                encrypted_token=encrypted_token,
                repo_full_name=repo_full_name,
                file_path=pdf_path,
                content=pdf_content,
                commit_message=f"Add compiled PDF for {company} - {role}",
            )

        logger.info(
            f"Committed application to {repo_full_name}/{dir_path} "
            f"(resume={resume_sha[:8]}, meta={metadata_sha[:8]})"
        )

        return {
            "dir_path": dir_path,
            "resume_sha": resume_sha,
            "metadata_sha": metadata_sha,
            "pdf_sha": pdf_sha,
        }

    # ══════════════════════════════════════════════════════
    # SEARCH & COMPARISON
    # ══════════════════════════════════════════════════════

    @github_circuit
    async def find_previous_applications(
        self,
        encrypted_token: str,
        repo_full_name: str,
        company: str | None = None,
    ) -> list[dict[str, Any]]:
        """
        Find previous applications, optionally filtered by company.

        Returns list of application metadata from the repo.
        Used by the "smart reuse" feature to suggest tweaking
        a previous resume instead of starting from scratch.
        """
        token = self._decrypt_token(encrypted_token)
        headers = self._build_headers(token)

        async with httpx.AsyncClient(timeout=15.0) as client:
            # List the applications directory
            resp = await client.get(
                f"{self.BASE_URL}/repos/{repo_full_name}/contents/applications",
                headers=headers,
            )

            if resp.status_code == 404:
                return []  # No applications yet

            self._check_response(resp)
            contents = resp.json()

            # Filter for directories only
            dirs = [item for item in contents if item["type"] == "dir"]

            # Filter by company if specified
            if company:
                safe_company = self._sanitize_path(company)
                dirs = [d for d in dirs if d["name"].startswith(safe_company)]

            # Fetch metadata for each application
            applications: list[dict[str, Any]] = []
            for d in dirs[:20]:  # Limit to 20 most recent
                try:
                    meta_resp = await client.get(
                        f"{self.BASE_URL}/repos/{repo_full_name}/contents/{d['path']}/metadata.json",
                        headers=headers,
                    )
                    if meta_resp.status_code == 200:
                        content_b64 = meta_resp.json().get("content", "")
                        meta_json = base64.b64decode(content_b64).decode("utf-8")
                        meta = json.loads(meta_json)
                        meta["_dir_name"] = d["name"]
                        meta["_dir_path"] = d["path"]
                        applications.append(meta)
                except Exception as e:
                    logger.warning(f"Failed to read metadata for {d['path']}: {e}")
                    continue

            # Sort by date (newest first)
            applications.sort(
                key=lambda x: x.get("committed_at", ""),
                reverse=True,
            )

            return applications

    @github_circuit
    async def download_file(
        self,
        encrypted_token: str,
        repo_full_name: str,
        file_path: str,
    ) -> bytes:
        """Download a file from the repo. Returns raw bytes."""
        token = self._decrypt_token(encrypted_token)
        headers = self._build_headers(token)

        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                f"{self.BASE_URL}/repos/{repo_full_name}/contents/{file_path}",
                headers=headers,
            )
            self._check_response(resp)
            content_b64 = resp.json().get("content", "")
            return base64.b64decode(content_b64)

    # ══════════════════════════════════════════════════════
    # INTERNAL HELPERS
    # ══════════════════════════════════════════════════════

    async def _commit_file(
        self,
        encrypted_token: str,
        repo_full_name: str,
        file_path: str,
        content: bytes,
        commit_message: str,
    ) -> str:
        """
        Create or update a file in the repo.

        If the file already exists, we need its SHA to update it.
        Returns the new commit SHA.
        """
        token = self._decrypt_token(encrypted_token)
        headers = self._build_headers(token)

        async with httpx.AsyncClient(timeout=15.0) as client:
            # Check if file exists (need SHA for update)
            existing_sha = None
            existing_resp = await client.get(
                f"{self.BASE_URL}/repos/{repo_full_name}/contents/{file_path}",
                headers=headers,
            )
            if existing_resp.status_code == 200:
                existing_sha = existing_resp.json().get("sha")

            # Build request
            data: dict[str, Any] = {
                "message": commit_message,
                "content": base64.b64encode(content).decode("ascii"),
            }
            if existing_sha:
                data["sha"] = existing_sha

            # Create/update the file
            resp = await client.put(
                f"{self.BASE_URL}/repos/{repo_full_name}/contents/{file_path}",
                headers=headers,
                json=data,
            )
            self._check_response(resp)

            return resp.json().get("commit", {}).get("sha", "unknown")

    @staticmethod
    def _sanitize_path(name: str) -> str:
        """
        Convert a company/role name into a safe directory name.

        "Google LLC" -> "google-llc"
        "Senior ML Engineer" -> "senior-ml-engineer"
        """
        import re
        sanitized = name.lower().strip()
        sanitized = re.sub(r"[^a-z0-9\s-]", "", sanitized)
        sanitized = re.sub(r"\s+", "-", sanitized)
        sanitized = re.sub(r"-+", "-", sanitized)
        return sanitized.strip("-")

    @staticmethod
    def _check_response(resp: httpx.Response) -> None:
        """Check GitHub API response and raise appropriate errors."""
        if resp.status_code == 401:
            raise GitHubAuthError(
                "GitHub token is invalid or expired. "
                "Please reconnect your GitHub account in settings."
            )
        if resp.status_code == 403:
            remaining = resp.headers.get("X-RateLimit-Remaining", "?")
            if remaining == "0":
                reset_time = resp.headers.get("X-RateLimit-Reset", "?")
                raise GitHubRateLimitError(
                    f"GitHub API rate limit exceeded. Resets at: {reset_time}"
                )
            raise GitHubError(f"GitHub API forbidden: {resp.text[:200]}")
        if resp.status_code == 404:
            raise GitHubError(f"GitHub resource not found: {resp.url}")
        if resp.status_code >= 400:
            raise GitHubError(
                f"GitHub API error {resp.status_code}: {resp.text[:300]}"
            )
