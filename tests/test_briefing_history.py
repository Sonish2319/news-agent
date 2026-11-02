"""
Tests for the briefing-history system and repeat-email prevention.

Tests here focus on the database helpers (get_briefed_hashes,
record_briefing_stories) and the comparison / trend-annotation module.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from news_agent.models import RankedStory
from news_agent.processing.comparison import annotate_trends
from news_agent.storage.database import (
    get_briefed_hashes,
    record_briefing_stories,
    start_run,
)
from tests.conftest import make_ranked, make_story


# ── Briefing history DB helpers ───────────────────────────────────────────────

class TestBriefingHistoryDb:
    def test_record_and_retrieve_hashes(self, fake_settings, in_memory_db):
        start_run("run-1")
        record_briefing_stories("run-1", "a@b.com", ["hash-1", "hash-2"])

        hashes = get_briefed_hashes("a@b.com", window_hours=24)
        assert "hash-1" in hashes
        assert "hash-2" in hashes

    def test_window_excludes_old_records(self, fake_settings, in_memory_db):
        """Records older than the window are NOT returned."""
        start_run("run-old")
        old_time = (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat()

        # Insert the old record directly, bypassing record_briefing_stories
        # which always uses NOW.
        conn = sqlite3.connect(str(in_memory_db))
        conn.execute(
            "INSERT INTO briefing_history "
            "(run_id, recipient, content_hash, briefed_at) VALUES (?,?,?,?)",
            ("run-old", "a@b.com", "old-hash", old_time),
        )
        conn.commit()
        conn.close()

        hashes = get_briefed_hashes("a@b.com", window_hours=24)
        assert "old-hash" not in hashes

    def test_window_includes_recent_records(self, fake_settings, in_memory_db):
        start_run("run-recent")
        record_briefing_stories("run-recent", "a@b.com", ["recent-hash"])

        hashes = get_briefed_hashes("a@b.com", window_hours=1)
        assert "recent-hash" in hashes

    def test_recipient_isolation(self, fake_settings, in_memory_db):
        start_run("run-alice")
        record_briefing_stories("run-alice", "alice@ex.com", ["hash-x"])

        assert "hash-x" in get_briefed_hashes("alice@ex.com", 24)
        assert "hash-x" not in get_briefed_hashes("bob@ex.com", 24)

    def test_empty_hash_list_is_no_op(self, fake_settings, in_memory_db):
        """Persisting an empty hash list writes nothing to the DB."""
        start_run("run-empty")
        record_briefing_stories("run-empty", "a@b.com", [])

        conn = sqlite3.connect(str(in_memory_db))
        rows = conn.execute("SELECT * FROM briefing_history").fetchall()
        conn.close()
        assert len(rows) == 0


# ── Trend annotation ──────────────────────────────────────────────────────────

class TestTrendAnnotation:
    def _briefing(self, stories):
        return [(make_ranked(id=i), s) for i, s in enumerate(stories)]

    def test_all_new_when_no_history(self, fake_settings, in_memory_db):
        """With no prior history every story is tagged 'new'."""
        stories = [make_story(f"T{i}", f"https://ex.com/{i}") for i in range(3)]
        briefing = self._briefing(stories)

        result = annotate_trends(briefing, recipient="a@b.com")
        assert all(r.trend == "new" for r, _ in result)

    def test_existing_hash_tagged_ongoing(self, fake_settings, in_memory_db):
        """A story whose hash is in history gets tagged 'ongoing'."""
        story = make_story("Ongoing story", "https://ex.com/ongoing")

        # Simulate it was in yesterday's briefing.
        start_run("yesterday-run")
        record_briefing_stories("yesterday-run", "a@b.com", [story.content_hash])

        briefing = [(make_ranked(id=0), story)]
        result = annotate_trends(briefing, recipient="a@b.com", window_hours=28)

        assert result[0][0].trend == "ongoing"

    def test_new_story_alongside_ongoing(self, fake_settings, in_memory_db):
        """Mixed briefing: one old, one new → correct tags on each."""
        old_story = make_story("Old story", "https://ex.com/old")
        new_story = make_story("New story", "https://ex.com/new")

        start_run("past-run")
        record_briefing_stories("past-run", "a@b.com", [old_story.content_hash])

        briefing = [
            (make_ranked(id=0), old_story),
            (make_ranked(id=1), new_story),
        ]
        result = annotate_trends(briefing, recipient="a@b.com", window_hours=28)

        trend_map = {str(orig.url): ranked.trend for ranked, orig in result}
        assert trend_map["https://ex.com/old"] == "ongoing"
        assert trend_map["https://ex.com/new"] == "new"

    def test_annotation_does_not_alter_other_fields(self, fake_settings, in_memory_db):
        """annotate_trends must not change score, headline, or other fields."""
        story = make_story("Unchanged story", "https://ex.com/x")
        ranked = make_ranked(id=0, score=8, headline="Original headline")

        result = annotate_trends([(ranked, story)], recipient="a@b.com")

        updated_ranked, _ = result[0]
        assert updated_ranked.score == 8
        assert updated_ranked.headline == "Original headline"
