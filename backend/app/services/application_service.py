"""
Application Tracking Service.

Manages the lifecycle of job applications in the database.
Each application tracks: company, role, resume version, status, and similarity.

This service coordinates between:
- Database (application records)
- GitHub (resume storage)
- Tailoring pipeline (resume rewriting)
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import select, func, desc
from sqlalchemy.ext.asyncio import AsyncSession
from loguru import logger

from app.models.application import Application
from app.models.user import User
from app.utils.hashing import hash_jd


class ApplicationService:
    """
    CRUD operations for job applications.

    Every method requires a database session (injected by FastAPI).
    """

    async def create_application(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
        company_name: str,
        role_title: str,
        job_url: str | None,
        platform: str,
        job_description: str,
        git_path: str,
        rewrite_strategy: str | None = None,
        similarity_score: float | None = None,
        similar_to_id: uuid.UUID | None = None,
        changes_summary: str | None = None,
    ) -> Application:
        """
        Create a new application record.

        Called after resume tailoring + GitHub commit succeeds.
        """
        application = Application(
            id=uuid.uuid4(),
            user_id=user_id,
            company_name=company_name,
            role_title=role_title,
            job_url=job_url,
            platform=platform,
            jd_hash=hash_jd(job_description),
            git_path=git_path,
            rewrite_strategy=rewrite_strategy,
            similarity_score=similarity_score,
            similar_to_application_id=similar_to_id,
            changes_summary=changes_summary,
            status="tailored",
        )

        db.add(application)
        await db.flush()  # Get the ID without committing

        logger.info(
            f"Created application: {company_name} - {role_title} "
            f"(id={application.id}, strategy={rewrite_strategy})"
        )

        return application

    async def get_application(
        self,
        db: AsyncSession,
        application_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> Application | None:
        """Get a single application by ID (scoped to user)."""
        result = await db.execute(
            select(Application).where(
                Application.id == application_id,
                Application.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()

    async def list_applications(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
        page: int = 1,
        per_page: int = 20,
        company_filter: str | None = None,
        status_filter: str | None = None,
    ) -> tuple[list[Application], int]:
        """
        List applications with pagination and optional filters.

        Returns (applications, total_count).
        """
        # Build base query
        query = select(Application).where(Application.user_id == user_id)
        count_query = select(func.count(Application.id)).where(
            Application.user_id == user_id
        )

        # Apply filters
        if company_filter:
            query = query.where(
                Application.company_name.ilike(f"%{company_filter}%")
            )
            count_query = count_query.where(
                Application.company_name.ilike(f"%{company_filter}%")
            )

        if status_filter:
            query = query.where(Application.status == status_filter)
            count_query = count_query.where(Application.status == status_filter)

        # Get total count
        total_result = await db.execute(count_query)
        total = total_result.scalar() or 0

        # Get paginated results
        offset = (page - 1) * per_page
        query = query.order_by(desc(Application.created_at)).offset(offset).limit(per_page)

        result = await db.execute(query)
        applications = list(result.scalars().all())

        return applications, total

    async def update_status(
        self,
        db: AsyncSession,
        application_id: uuid.UUID,
        user_id: uuid.UUID,
        new_status: str,
    ) -> Application | None:
        """
        Update the status of an application.

        Valid transitions: draft → tailored → applied → rejected/interview → offer
        """
        valid_statuses = {"draft", "tailored", "applied", "rejected", "interview", "offer"}
        if new_status not in valid_statuses:
            raise ValueError(f"Invalid status: {new_status}. Must be one of {valid_statuses}")

        application = await self.get_application(db, application_id, user_id)
        if not application:
            return None

        old_status = application.status
        application.status = new_status

        logger.info(
            f"Application {application_id}: {old_status} → {new_status} "
            f"({application.company_name} - {application.role_title})"
        )

        return application

    async def find_similar(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
        jd_hash: str,
        company_name: str,
    ) -> Application | None:
        """
        Find the most similar previous application.

        First checks for exact JD match (same hash), then
        looks for same company applications.
        """
        # Exact JD match (user applied to exact same posting)
        result = await db.execute(
            select(Application)
            .where(
                Application.user_id == user_id,
                Application.jd_hash == jd_hash,
            )
            .order_by(desc(Application.created_at))
            .limit(1)
        )
        exact = result.scalar_one_or_none()
        if exact:
            return exact

        # Same company (different role/posting)
        result = await db.execute(
            select(Application)
            .where(
                Application.user_id == user_id,
                Application.company_name.ilike(f"%{company_name}%"),
            )
            .order_by(desc(Application.created_at))
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def get_stats(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
    ) -> dict:
        """Get application statistics for a user."""
        # Total count
        total_result = await db.execute(
            select(func.count(Application.id)).where(
                Application.user_id == user_id
            )
        )
        total = total_result.scalar() or 0

        # Count by status
        status_result = await db.execute(
            select(Application.status, func.count(Application.id))
            .where(Application.user_id == user_id)
            .group_by(Application.status)
        )
        status_counts = {row[0]: row[1] for row in status_result.all()}

        # Unique companies
        company_result = await db.execute(
            select(func.count(func.distinct(Application.company_name)))
            .where(Application.user_id == user_id)
        )
        unique_companies = company_result.scalar() or 0

        return {
            "total_applications": total,
            "unique_companies": unique_companies,
            "by_status": status_counts,
        }