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
        app_service = ApplicationService(db_session)

        app = await app_service.create_application(
            user_id=test_user.id,  # Use test_user fixture instead of random UUID
            company_name="Google",
            role_title="Senior Software Engineer",
            job_url="https://careers.google.com/jobs/123",
            platform="linkedin",
            job_description="Looking for Python engineer with 5 years experience",
            strategy="moderate",
        )

        assert app is not None
        assert app.user_id == test_user.id
        assert app.company_name == "Google"
        assert app.status == "tailored"
        assert app.jd_hash is not None

    @pytest.mark.asyncio
    async def test_update_status(self, db_session, test_user):
        """Test updating application status."""
        app_service = ApplicationService(db_session)

        # First create an application using the real test_user
        app = await app_service.create_application(
            user_id=test_user.id,  # Use test_user fixture
            company_name="Meta",
            role_title="ML Engineer",
            job_url=None,
            platform="manual",
            job_description="ML engineer role",
            strategy=None,
        )

        # Update status
        updated = await app_service.update_status(app.id, "applied")
        assert updated.status == "applied"

    @pytest.mark.asyncio
    async def test_invalid_status_raises(self, db_session, test_user):
        """Test that invalid status raises error."""
        app_service = ApplicationService(db_session)

        app = await app_service.create_application(
            user_id=test_user.id,  # Use test_user fixture
            company_name="Test",
            role_title="Test Role",
            job_url=None,
            platform="manual",
            job_description="Test job",
            strategy=None,
        )

        with pytest.raises(ValueError):
            await app_service.update_status(app.id, "invalid_status")

    @pytest.mark.asyncio
    async def test_list_applications_empty(self, db_session, test_user):
        """Test listing applications when user has none (but user exists)."""
        app_service = ApplicationService(db_session)

        # Query for the test_user (who has no applications yet)
        apps, total = await app_service.list_applications(
            user_id=test_user.id, skip=0, limit=10  # Use real user ID
        )

        assert len(apps) == 0
        assert total == 0

    @pytest.mark.asyncio
    async def test_find_similar_by_jd_hash(self, db_session, test_user):
        """Test finding similar applications by JD hash."""
        app_service = ApplicationService(db_session)

        # Create first application for test_user
        job_desc = "Software engineer with Python experience"
        app1 = await app_service.create_application(
            user_id=test_user.id,  # Same user
            company_name="Stripe",
            role_title="Python Developer",
            job_url=None,
            platform="manual",
            job_description=job_desc,
            strategy=None,
        )

        # Create second application for same user with same description
        app2 = await app_service.create_application(
            user_id=test_user.id,  # Same user
            company_name="Square",
            role_title="Backend Developer",
            job_url=None,
            platform="manual",
            job_description=job_desc,  # Same description = same hash
            strategy=None,
        )

        # Find similar apps for app2 (excluding itself)
        similar = await app_service.find_similar_by_jd_hash(
            user_id=test_user.id, jd_hash=app2.jd_hash, exclude_id=app2.id
        )

        # Should find app1 as similar
        assert len(similar) >= 1
        assert any(s.id == app1.id for s in similar)

    @pytest.mark.asyncio
    async def test_find_similar_different_user(self, db_session, test_user):
        """Test that similar applications from different users are not returned."""
        app_service = ApplicationService(db_session)

        # Create application for test_user
        app = await app_service.create_application(
            user_id=test_user.id,
            company_name="Apple",
            role_title="iOS Dev",
            job_url=None,
            platform="manual",
            job_description="iOS developer role",
            strategy=None,
        )

        # Create a second user manually in this test
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

        # Create application for other user with same job description
        await app_service.create_application(
            user_id=other_user.id,  # Different user
            company_name="Google",
            role_title="Android Dev",
            job_url=None,
            platform="manual",
            job_description="iOS developer role",  # Same description
            strategy=None,
        )

        # Search should only return apps for test_user
        similar = await app_service.find_similar_by_jd_hash(
            user_id=test_user.id, jd_hash=app.jd_hash, exclude_id=None  # Query as test_user
        )

        # Should only find the one belonging to test_user, not other_user
        assert all(s.user_id == test_user.id for s in similar)
        assert not any(s.user_id == other_user.id for s in similar)
