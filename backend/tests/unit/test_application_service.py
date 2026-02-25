"""
Tests for Application Service.
"""

import uuid

import pytest

from app.models.user import User
from app.services.application_service import ApplicationService


class TestApplicationService:

    @pytest.mark.asyncio
    async def test_create_application(self, db_session, test_user):
        """Test creating an application with valid data."""
        app_service = ApplicationService()

        app = await app_service.create_application(
            db=db_session,
            user_id=test_user.id,
            company_name="Google",
            role_title="Senior Software Engineer",
            job_url="https://careers.google.com/jobs/123",
            platform="linkedin",
            job_description="Looking for Python engineer with 5 years experience",
            git_path="versions/Narendranath_Google_SWE.tex",
            rewrite_strategy="moderate",
        )

        assert app is not None
        assert app.user_id == test_user.id
        assert app.company_name == "Google"
        assert app.status == "tailored"
        assert app.jd_hash is not None

    @pytest.mark.asyncio
    async def test_update_status(self, db_session, test_user):
        """Test updating application status."""
        app_service = ApplicationService()

        app = await app_service.create_application(
            db=db_session,
            user_id=test_user.id,
            company_name="Meta",
            role_title="ML Engineer",
            job_url=None,
            platform="manual",
            job_description="ML engineer role",
            git_path="versions/Narendranath_Meta_MLE.tex",
        )

        updated = await app_service.update_status(
            db=db_session,
            application_id=app.id,
            user_id=test_user.id,
            new_status="applied",
        )
        assert updated.status == "applied"

    @pytest.mark.asyncio
    async def test_invalid_status_raises(self, db_session, test_user):
        """Test that invalid status raises error."""
        app_service = ApplicationService()

        app = await app_service.create_application(
            db=db_session,
            user_id=test_user.id,
            company_name="Test",
            role_title="Test Role",
            job_url=None,
            platform="manual",
            job_description="Test job",
            git_path="versions/Narendranath_Test_SWE.tex",
        )

        with pytest.raises(ValueError):
            await app_service.update_status(
                db=db_session,
                application_id=app.id,
                user_id=test_user.id,
                new_status="invalid_status",
            )

    @pytest.mark.asyncio
    async def test_list_applications_empty(self, db_session, test_user):
        """Test listing applications when user has none."""
        app_service = ApplicationService()

        apps, total = await app_service.list_applications(
            db=db_session,
            user_id=test_user.id,
            page=1,
            per_page=10,
        )

        assert len(apps) == 0
        assert total == 0

    @pytest.mark.asyncio
    async def test_find_similar_by_jd_hash(self, db_session, test_user):
        """Test finding similar applications by JD hash."""
        app_service = ApplicationService()

        job_desc = "Software engineer with Python experience"
        app1 = await app_service.create_application(
            db=db_session,
            user_id=test_user.id,
            company_name="Stripe",
            role_title="Python Developer",
            job_url=None,
            platform="manual",
            job_description=job_desc,
            git_path="versions/Narendranath_Stripe_DE.tex",
        )

        await app_service.create_application(
            db=db_session,
            user_id=test_user.id,
            company_name="Square",
            role_title="Backend Developer",
            job_url=None,
            platform="manual",
            job_description=job_desc,  # Same description = same hash
            git_path="versions/Narendranath_Square_DE.tex",
        )

        # find_similar returns the most recent exact match — app2 matches app1's hash
        similar = await app_service.find_similar(
            db=db_session,
            user_id=test_user.id,
            jd_hash=app1.jd_hash,
            company_name="Stripe",
        )

        assert similar is not None
        assert similar.user_id == test_user.id

    @pytest.mark.asyncio
    async def test_find_similar_different_user(self, db_session, test_user):
        """Test that similar applications from different users are not returned."""
        app_service = ApplicationService()

        app = await app_service.create_application(
            db=db_session,
            user_id=test_user.id,
            company_name="Apple",
            role_title="iOS Dev",
            job_url=None,
            platform="manual",
            job_description="iOS developer role",
            git_path="versions/Narendranath_Apple_iOS.tex",
        )

        other_user = User(
            id=uuid.uuid4(),
            clerk_id=f"other_{uuid.uuid4().hex[:8]}",
            email_hash="b" * 64,
            github_username="otheruser",
            resume_repo_name="resume-vault",
            is_active=True,
        )
        db_session.add(other_user)
        await db_session.flush()

        await app_service.create_application(
            db=db_session,
            user_id=other_user.id,
            company_name="Apple",
            role_title="Android Dev",
            job_url=None,
            platform="manual",
            job_description="iOS developer role",  # Same description
            git_path="versions/Narendranath_Apple_Android.tex",
        )

        # Search scoped to test_user — should not return other_user's app
        similar = await app_service.find_similar(
            db=db_session,
            user_id=test_user.id,
            jd_hash=app.jd_hash,
            company_name="Apple",
        )

        if similar:
            assert similar.user_id == test_user.id
