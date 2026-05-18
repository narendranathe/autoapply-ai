"""Verify all three new models are registered in Base.metadata."""

from app.models.base import Base


def test_story_entries_table_registered():
    assert "story_entries" in Base.metadata.tables


def test_offer_evaluations_table_registered():
    assert "offer_evaluations" in Base.metadata.tables


def test_portal_scan_cache_table_registered():
    assert "portal_scan_cache" in Base.metadata.tables
