"""
Tests for SMTP delivery failure paths.

Covers:
  - Authentication failure (SMTPAuthenticationError)
  - Connection refused / unavailable SMTP server
  - Send timeout
  - Retry logic: retries up to smtp_max_retries times with delays
  - SmtpDeliveryError raised after all retries exhausted
  - Failed delivery is recorded in the database
  - Successful delivery is recorded in the database
  - Pipeline marks run as 'partial' when email fails
"""

from __future__ import annotations

import smtplib
from unittest.mock import MagicMock, call, patch

import pytest

from news_agent.delivery.email_sender import SmtpDeliveryError, send_email
from tests.conftest import make_ranked, make_story

# Module path used when patching settings inside email_sender
_ES = "news_agent.delivery.email_sender"


# ── Helpers ──────────────────────────────────────────────────────────────────

def _sample_briefing(n: int = 2):
    stories = [make_story(f"Title {i}", f"https://ex.com/{i}") for i in range(n)]
    ranked = [make_ranked(id=i, score=8) for i in range(n)]
    return list(zip(ranked, stories))


# ── SMTP error types ─────────────────────────────────────────────────────────

class TestSmtpErrors:
    @patch(f"{_ES}.smtplib.SMTP")
    @patch(f"{_ES}.time.sleep")
    def test_auth_failure_retries_then_raises(
        self, mock_sleep, mock_smtp_cls, fake_settings
    ):
        """SMTPAuthenticationError triggers retries then SmtpDeliveryError."""
        mock_smtp = MagicMock()
        mock_smtp.__enter__ = lambda s: s
        mock_smtp.__exit__ = MagicMock(return_value=False)
        mock_smtp.login.side_effect = smtplib.SMTPAuthenticationError(
            535, b"Authentication credentials invalid"
        )
        mock_smtp_cls.return_value = mock_smtp

        briefing = _sample_briefing()
        with patch(f"{_ES}.get_settings", return_value=fake_settings):
            with pytest.raises(SmtpDeliveryError, match="SMTP delivery"):
                send_email(briefing)

        # smtp_max_retries=1 → 2 total attempts
        assert mock_smtp_cls.call_count == 2

    @patch(f"{_ES}.smtplib.SMTP")
    @patch(f"{_ES}.time.sleep")
    def test_connection_refused_retries_then_raises(
        self, mock_sleep, mock_smtp_cls, fake_settings
    ):
        """OSError (connection refused) triggers retries then SmtpDeliveryError."""
        mock_smtp_cls.side_effect = OSError("Connection refused")

        briefing = _sample_briefing()
        with patch(f"{_ES}.get_settings", return_value=fake_settings):
            with pytest.raises(SmtpDeliveryError):
                send_email(briefing)

        assert mock_smtp_cls.call_count == 2

    @patch(f"{_ES}.smtplib.SMTP")
    @patch(f"{_ES}.time.sleep")
    def test_timeout_retries_then_raises(
        self, mock_sleep, mock_smtp_cls, fake_settings
    ):
        """TimeoutError triggers retries then SmtpDeliveryError."""
        mock_smtp_cls.side_effect = TimeoutError("timed out")

        briefing = _sample_briefing()
        with patch(f"{_ES}.get_settings", return_value=fake_settings):
            with pytest.raises(SmtpDeliveryError):
                send_email(briefing)

        assert mock_smtp_cls.call_count == 2

    @patch(f"{_ES}.smtplib.SMTP")
    @patch(f"{_ES}.time.sleep")
    def test_retry_sleep_delays(self, mock_sleep, mock_smtp_cls, fake_settings):
        """Sleep delay is 5s before the first retry (smtp_max_retries=1 → 1 sleep)."""
        mock_smtp_cls.side_effect = OSError("refused")

        with patch(f"{_ES}.get_settings", return_value=fake_settings):
            with pytest.raises(SmtpDeliveryError):
                send_email(_sample_briefing())

        # smtp_max_retries=1 → 1 sleep of 5s before the second attempt
        mock_sleep.assert_called_once_with(5)

    @patch(f"{_ES}.smtplib.SMTP")
    @patch(f"{_ES}.time.sleep")
    def test_succeeds_on_second_attempt(self, mock_sleep, mock_smtp_cls, fake_settings):
        """Recovery on the second SMTP attempt returns without error."""
        fail_ctx = MagicMock()
        fail_ctx.__enter__ = lambda s: s
        fail_ctx.__exit__ = MagicMock(return_value=False)
        fail_ctx.login.side_effect = smtplib.SMTPException("transient error")

        ok_ctx = MagicMock()
        ok_ctx.__enter__ = lambda s: s
        ok_ctx.__exit__ = MagicMock(return_value=False)

        mock_smtp_cls.side_effect = [fail_ctx, ok_ctx]

        with patch(f"{_ES}.get_settings", return_value=fake_settings):
            # Should not raise
            send_email(_sample_briefing())

        assert mock_smtp_cls.call_count == 2


# ── Zero retries ─────────────────────────────────────────────────────────────

class TestSmtpNoRetry:
    @patch(f"{_ES}.smtplib.SMTP")
    @patch(f"{_ES}.time.sleep")
    def test_no_retry_when_smtp_max_retries_zero(
        self, mock_sleep, mock_smtp_cls, fake_settings
    ):
        """With smtp_max_retries=0 there is exactly 1 attempt and no sleep."""
        # Temporarily set retries to 0
        import dataclasses
        zero_retry_settings = fake_settings.model_copy(
            update={"smtp_max_retries": 0}
        )
        mock_smtp_cls.side_effect = OSError("refused")

        with patch(f"{_ES}.get_settings", return_value=zero_retry_settings):
            with pytest.raises(SmtpDeliveryError):
                send_email(_sample_briefing())

        assert mock_smtp_cls.call_count == 1
        mock_sleep.assert_not_called()


# ── Delivery recording via pipeline ──────────────────────────────────────────

class TestDeliveryRecording:
    @patch("news_agent.pipeline.send_email")
    @patch("news_agent.pipeline.rank_stories")
    @patch("news_agent.pipeline.collect_news")
    @patch("news_agent.pipeline.annotate_trends", side_effect=lambda b, **kw: b)
    def test_failed_delivery_recorded_in_db(
        self,
        _mock_trends,
        mock_collect,
        mock_rank,
        mock_send,
        fake_settings,
        in_memory_db,
    ):
        """When SMTP fails the failure is written to the deliveries table."""
        import sqlite3

        from news_agent.pipeline import run_pipeline

        stories = [
            make_story("S1", "https://ex.com/1"),
            make_story("S2", "https://ex.com/2"),
        ]
        mock_collect.return_value = stories
        mock_rank.return_value = [make_ranked(id=0), make_ranked(id=1)]
        mock_send.side_effect = SmtpDeliveryError("Send failed")

        with pytest.raises(SmtpDeliveryError):
            run_pipeline(country="Nepal", email_to="bob@example.com")

        conn = sqlite3.connect(str(in_memory_db))
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM deliveries").fetchall()
        conn.close()

        assert len(rows) == 1
        assert rows[0]["status"] == "failed"
        assert "Send failed" in rows[0]["error"]
        assert rows[0]["recipient"] == "bob@example.com"

    @patch("news_agent.pipeline.send_email")
    @patch("news_agent.pipeline.rank_stories")
    @patch("news_agent.pipeline.collect_news")
    @patch("news_agent.pipeline.annotate_trends", side_effect=lambda b, **kw: b)
    def test_successful_delivery_recorded_in_db(
        self,
        _mock_trends,
        mock_collect,
        mock_rank,
        mock_send,
        fake_settings,
        in_memory_db,
    ):
        """When email succeeds the 'sent' status is written to deliveries."""
        import sqlite3

        from news_agent.pipeline import run_pipeline

        stories = [make_story("S1", "https://ex.com/1")]
        mock_collect.return_value = stories
        mock_rank.return_value = [make_ranked(id=0)]
        mock_send.return_value = None

        run_pipeline(country="Nepal", email_to="alice@example.com")

        conn = sqlite3.connect(str(in_memory_db))
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM deliveries").fetchall()
        conn.close()

        assert len(rows) == 1
        assert rows[0]["status"] == "sent"
        assert rows[0]["error"] is None

    @patch("news_agent.pipeline.send_email")
    @patch("news_agent.pipeline.rank_stories")
    @patch("news_agent.pipeline.collect_news")
    @patch("news_agent.pipeline.annotate_trends", side_effect=lambda b, **kw: b)
    def test_run_status_partial_on_smtp_failure(
        self,
        _mock_trends,
        mock_collect,
        mock_rank,
        mock_send,
        fake_settings,
        in_memory_db,
    ):
        """The run record shows 'partial' when email fails after ranking."""
        import sqlite3

        from news_agent.pipeline import run_pipeline

        stories = [make_story("S1", "https://ex.com/1")]
        mock_collect.return_value = stories
        mock_rank.return_value = [make_ranked(id=0)]
        mock_send.side_effect = SmtpDeliveryError("All retries failed")

        with pytest.raises(SmtpDeliveryError):
            run_pipeline(country="Nepal")

        conn = sqlite3.connect(str(in_memory_db))
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT status FROM runs").fetchone()
        conn.close()

        assert row["status"] == "partial"
