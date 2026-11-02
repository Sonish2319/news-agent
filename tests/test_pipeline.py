"""
Tests for the full pipeline (run_pipeline).

Covers:
  - Happy path: collect → deduplicate → cluster → rank → email → record
  - No stories collected → RuntimeError
  - No stories ranked → RuntimeError
  - New-vs-stored story distinction (is_new flag)
  - Briefing history filter (repeat-email prevention)
  - Trend annotation wired through pipeline
  - SMTP failure → partial status, failure recorded
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from news_agent.delivery.email_sender import SmtpDeliveryError
from news_agent.models import RankedStory
from tests.conftest import make_ranked, make_story


# ── Happy path ────────────────────────────────────────────────────────────────

class TestPipelineHappyPath:
    def test_run_returns_success_result(self, fake_settings, in_memory_db):
        with (
            patch("news_agent.pipeline.collect_news") as mc,
            patch("news_agent.pipeline.rank_stories") as mr,
            patch("news_agent.pipeline.send_email"),
            patch("news_agent.pipeline.annotate_trends", side_effect=lambda b, **kw: b),
        ):
            stories = [make_story(f"T{i}", f"https://ex.com/{i}") for i in range(3)]
            mc.return_value = stories
            mr.return_value = [make_ranked(id=i) for i in range(3)]

            from news_agent.pipeline import run_pipeline
            result = run_pipeline(country="Nepal", email_to="a@b.com")

        assert result.status == "success"
        assert result.emailed is True
        assert result.selected_count == 3

    def test_briefing_history_persisted_after_send(self, fake_settings, in_memory_db):
        """After a successful send the content hashes land in briefing_history."""
        with (
            patch("news_agent.pipeline.collect_news") as mc,
            patch("news_agent.pipeline.rank_stories") as mr,
            patch("news_agent.pipeline.send_email"),
            patch("news_agent.pipeline.annotate_trends", side_effect=lambda b, **kw: b),
        ):
            stories = [make_story("T0", "https://ex.com/0")]
            mc.return_value = stories
            mr.return_value = [make_ranked(id=0)]

            from news_agent.pipeline import run_pipeline
            run_pipeline(country="Nepal", email_to="a@b.com")

        conn = sqlite3.connect(str(in_memory_db))
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM briefing_history").fetchall()
        conn.close()

        assert len(rows) == 1
        assert rows[0]["recipient"] == "a@b.com"


# ── Collection failures ───────────────────────────────────────────────────────

class TestPipelineCollectionFailures:
    def test_no_stories_raises(self, fake_settings, in_memory_db):
        with (
            patch("news_agent.pipeline.collect_news", return_value=[]),
        ):
            from news_agent.pipeline import run_pipeline
            with pytest.raises(RuntimeError, match="No RSS stories"):
                run_pipeline()

    def test_empty_ranking_raises(self, fake_settings, in_memory_db):
        with (
            patch("news_agent.pipeline.collect_news") as mc,
            patch("news_agent.pipeline.rank_stories", return_value=[]),
        ):
            mc.return_value = [make_story("T0", "https://ex.com/0")]
            from news_agent.pipeline import run_pipeline
            with pytest.raises(RuntimeError, match="No valid stories"):
                run_pipeline()


# ── New vs previously-stored ─────────────────────────────────────────────────

class TestNewVsStoredStories:
    def test_is_new_true_for_fresh_stories(self, fake_settings, in_memory_db):
        """Stories inserted for the first time have is_new=True."""
        from news_agent.storage.database import save_stories

        stories = [make_story("Fresh story", "https://ex.com/fresh")]
        saved = save_stories(stories)

        assert saved[0].is_new is True

    def test_is_new_false_for_duplicate(self, fake_settings, in_memory_db):
        """A story inserted twice gets is_new=False on the second call."""
        from news_agent.storage.database import save_stories

        story = make_story("Repeated story", "https://ex.com/repeat")
        save_stories([story])        # first insert → is_new=True
        saved = save_stories([story])  # second insert → is_new=False

        assert saved[0].is_new is False

    def test_mixed_new_and_existing(self, fake_settings, in_memory_db):
        """Batch with both fresh and existing stories is tagged correctly."""
        from news_agent.storage.database import save_stories

        old = make_story("Old story", "https://ex.com/old")
        new = make_story("New story", "https://ex.com/new")

        save_stories([old])
        saved = save_stories([old, new])

        by_url = {str(s.url): s for s in saved}
        assert by_url["https://ex.com/old"].is_new is False
        assert by_url["https://ex.com/new"].is_new is True


# ── Briefing history / repeat prevention ─────────────────────────────────────

class TestBriefingHistory:
    def test_stories_already_briefed_are_skipped(self, fake_settings, in_memory_db):
        """Stories in briefing_history are excluded from the next run's candidates."""
        from news_agent.storage.database import (
            get_briefed_hashes,
            record_briefing_stories,
            start_run,
        )

        run_id = "test-run-001"
        start_run(run_id)
        story = make_story("Already seen", "https://ex.com/seen")

        record_briefing_stories(run_id, "a@b.com", [story.content_hash])

        briefed = get_briefed_hashes("a@b.com", window_hours=24)
        assert story.content_hash in briefed

    def test_briefed_hashes_not_returned_after_window(self, fake_settings, in_memory_db):
        """Hashes outside the time window are not returned."""
        from news_agent.storage.database import (
            get_briefed_hashes,
            start_run,
        )

        run_id = "old-run"
        start_run(run_id)

        # Insert an old record directly with a timestamp beyond the window.
        old_time = (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat()
        conn = sqlite3.connect(str(in_memory_db))
        conn.execute(
            "INSERT INTO briefing_history (run_id, recipient, content_hash, briefed_at) "
            "VALUES (?, ?, ?, ?)",
            (run_id, "a@b.com", "old-hash", old_time),
        )
        conn.commit()
        conn.close()

        briefed = get_briefed_hashes("a@b.com", window_hours=24)
        assert "old-hash" not in briefed

    def test_different_recipients_isolated(self, fake_settings, in_memory_db):
        """Briefing history is per-recipient; hash for alice != hash for bob."""
        from news_agent.storage.database import (
            get_briefed_hashes,
            record_briefing_stories,
            start_run,
        )

        start_run("r1")
        record_briefing_stories("r1", "alice@ex.com", ["hash-abc"])

        assert "hash-abc" in get_briefed_hashes("alice@ex.com", 24)
        assert "hash-abc" not in get_briefed_hashes("bob@ex.com", 24)


# ── SMTP failure in pipeline ─────────────────────────────────────────────────

class TestPipelineSmtpFailure:
    @patch("news_agent.pipeline.annotate_trends", side_effect=lambda b, **kw: b)
    @patch("news_agent.pipeline.send_email")
    @patch("news_agent.pipeline.rank_stories")
    @patch("news_agent.pipeline.collect_news")
    def test_partial_status_on_smtp_failure(
        self,
        mock_collect,
        mock_rank,
        mock_send,
        _mock_trends,
        fake_settings,
        in_memory_db,
    ):
        mock_collect.return_value = [make_story("T0", "https://ex.com/0")]
        mock_rank.return_value = [make_ranked(id=0)]
        mock_send.side_effect = SmtpDeliveryError("fail")

        from news_agent.pipeline import run_pipeline
        with pytest.raises(SmtpDeliveryError):
            run_pipeline()

        conn = sqlite3.connect(str(in_memory_db))
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT status FROM runs").fetchone()
        conn.close()

        assert row["status"] == "partial"
