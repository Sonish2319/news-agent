"""
Shared pytest fixtures for the news-agent test suite.

All fixtures that patch the settings object use a minimal, credentials-free
``Settings`` so no real .env file is needed during tests.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from news_agent.models import RankedStory, Story


# ── Helpers ──────────────────────────────────────────────────────────────────

def make_story(
    title: str = "Test headline",
    url: str = "https://example.com/story",
    source: str = "Test Source",
    content_hash: str | None = None,
    is_new: bool = True,
    summary: str = "A test summary.",
) -> Story:
    return Story(
        title=title,
        summary=summary,
        source=source,
        url=url,
        collected_at=datetime.now(timezone.utc),
        content_hash=content_hash or f"hash-{url}",
        is_new=is_new,
    )


def make_ranked(
    id: int = 0,
    score: int = 7,
    headline: str = "Ranked headline",
    category: str = "World",
    summary: str = "A short summary for ranking.",
    why_it_matters: str = "It matters a lot.",
    trend: str = "new",
) -> RankedStory:
    return RankedStory(
        id=id,
        score=score,
        headline=headline,
        category=category,
        summary=summary,
        why_it_matters=why_it_matters,
        trend=trend,
    )


# ── Settings fixture ─────────────────────────────────────────────────────────

@pytest.fixture()
def fake_settings(tmp_path):
    """Return a Settings-like object with no real credentials.

    Patches get_settings in every module that imports it directly so all DB,
    email and ranking calls use the test configuration.
    """
    from news_agent.config import Settings, get_settings

    settings = Settings(
        ollama_model="test-model",
        ollama_url="http://localhost:11434",
        ollama_timeout=10,
        ollama_max_retries=3,
        gmail_address="test@example.com",
        gmail_app_password="fake-password",
        email_to="recipient@example.com",
        smtp_max_retries=1,
        top_stories=5,
        rss_entries_per_feed=5,
        database_path=tmp_path / "test.db",
        log_level="DEBUG",
        timezone_name="UTC",
        topic_preferences="",
        briefing_dedup_hours=20,
        breaking_news_hour=7,
        breaking_news_score_threshold=9,
        scheduler_enabled=False,
    )

    get_settings.cache_clear()

    # Patch every module that calls get_settings() so they all use the test DB.
    modules_to_patch = [
        "news_agent.config.get_settings",
        "news_agent.storage.database.get_settings",
        "news_agent.processing.ranking.get_settings",
        "news_agent.delivery.email_sender.get_settings",
        "news_agent.pipeline.get_settings",
        "news_agent.sources.rss.get_settings",
    ]

    patches = [patch(m, return_value=settings) for m in modules_to_patch]
    for p in patches:
        p.start()

    yield settings

    for p in patches:
        p.stop()

    get_settings.cache_clear()


# ── In-memory database fixture ────────────────────────────────────────────────

@pytest.fixture()
def in_memory_db(fake_settings):
    """Initialise a fresh SQLite database in the tmp_path for each test."""
    from news_agent.storage.database import initialize_database

    initialize_database()
    yield fake_settings.database_path


# ── Story fixtures ────────────────────────────────────────────────────────────

@pytest.fixture()
def sample_stories() -> list[Story]:
    return [
        make_story("Nepal quake kills dozens", "https://kathmandu.com/1", source="KPost"),
        make_story("India launches moon mission", "https://ndtv.com/2", source="NDTV"),
        make_story("Global markets rally", "https://bbc.com/3", source="BBC"),
        make_story("Tech giant releases AI model", "https://bbc.com/4", source="BBC"),
        make_story("Climate summit opens in Paris", "https://aljz.com/5", source="Al Jazeera"),
    ]


@pytest.fixture()
def sample_briefing(sample_stories) -> list[tuple[RankedStory, Story]]:
    return [
        (make_ranked(id=i, score=10 - i, headline=s.title), s)
        for i, s in enumerate(sample_stories[:3])
    ]
