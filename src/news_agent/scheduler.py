"""
Breaking-news scheduler.

Uses APScheduler to:
  1. Fire a daily briefing at the configured hour (BREAKING_NEWS_HOUR).
  2. Check every 30 minutes for stories scoring >= BREAKING_NEWS_SCORE_THRESHOLD
     that were collected since the last check; send a "⚡ Breaking News Alert"
     email when such stories exist.

Enable by setting ``SCHEDULER_ENABLED=true`` in your .env file.
Install the optional dependency:  pip install "apscheduler>=3.10"
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

logger = logging.getLogger(__name__)

try:
    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.triggers.cron import CronTrigger
    from apscheduler.triggers.interval import IntervalTrigger
    _APSCHEDULER_AVAILABLE = True
except ImportError:  # pragma: no cover
    _APSCHEDULER_AVAILABLE = False


# ── Breaking-news check state ────────────────────────────────────────────────

# Timestamp of the last breaking-news scan; updated after each alert email.
_last_breaking_check: datetime = datetime.now(timezone.utc) - timedelta(hours=1)


def _run_daily_briefing() -> None:
    """Trigger the full pipeline for the configured recipient."""
    from news_agent.config import get_settings
    from news_agent.pipeline import run_pipeline

    settings = get_settings()
    logger.info("Scheduler: starting scheduled daily briefing")
    try:
        result = run_pipeline(country="Nepal")
        logger.info(
            "Scheduler: daily briefing finished — run_id=%s stories=%d",
            result.run_id, result.selected_count,
        )
    except Exception:
        logger.exception("Scheduler: daily briefing failed")


def _check_breaking_news() -> None:
    """Scan recent stories and send an alert if any score above threshold."""
    global _last_breaking_check

    from news_agent.config import get_settings
    from news_agent.delivery.email_sender import send_breaking_news_email
    from news_agent.processing.ranking import rank_stories
    from news_agent.sources.rss import collect_news
    from news_agent.processing.deduplication import deduplicate_stories
    from news_agent.storage.database import save_stories

    settings = get_settings()
    threshold = settings.breaking_news_score_threshold
    since = _last_breaking_check

    logger.debug(
        "Scheduler: checking for breaking news since %s (threshold=%d)",
        since.isoformat(), threshold,
    )

    try:
        stories = collect_news(country="Nepal")
        if not stories:
            return

        unique = deduplicate_stories(stories)
        persisted = save_stories(unique)

        ranked = rank_stories(persisted, country="Nepal", top_stories=5)
        breaking = [(r, persisted[r.id]) for r in ranked if r.score >= threshold]

        if breaking:
            logger.info(
                "Scheduler: %d breaking stories found, sending alert",
                len(breaking),
            )
            send_breaking_news_email(breaking)
            _last_breaking_check = datetime.now(timezone.utc)
        else:
            logger.debug("Scheduler: no breaking stories above threshold")

    except Exception:
        logger.exception("Scheduler: breaking-news check failed")


# ── Public API ────────────────────────────────────────────────────────────────

_scheduler: "BackgroundScheduler | None" = None


def get_scheduler() -> "BackgroundScheduler | None":
    return _scheduler


def start_scheduler() -> bool:
    """Start the background scheduler.  Returns True if started successfully."""
    global _scheduler

    if not _APSCHEDULER_AVAILABLE:
        logger.warning(
            "APScheduler is not installed; scheduler will not start. "
            "Run: pip install 'apscheduler>=3.10'"
        )
        return False

    from news_agent.config import get_settings
    settings = get_settings()

    if not settings.scheduler_enabled:
        logger.info("Scheduler disabled (SCHEDULER_ENABLED=false)")
        return False

    if _scheduler is not None and _scheduler.running:
        logger.info("Scheduler already running")
        return True

    _scheduler = BackgroundScheduler(timezone=settings.timezone)

    # Daily briefing job.
    _scheduler.add_job(
        _run_daily_briefing,
        trigger=CronTrigger(hour=settings.breaking_news_hour, minute=0),
        id="daily_briefing",
        name="Daily news briefing",
        replace_existing=True,
        misfire_grace_time=300,
    )

    # Breaking-news check every 30 minutes.
    _scheduler.add_job(
        _check_breaking_news,
        trigger=IntervalTrigger(minutes=30),
        id="breaking_news_check",
        name="Breaking news alert check",
        replace_existing=True,
        misfire_grace_time=120,
    )

    _scheduler.start()
    logger.info(
        "Scheduler started: daily briefing at %02d:00, "
        "breaking-news checks every 30 min",
        settings.breaking_news_hour,
    )
    return True


def stop_scheduler() -> None:
    """Gracefully shut down the background scheduler."""
    global _scheduler

    if _scheduler is not None and _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped")

    _scheduler = None


def scheduler_status() -> dict:
    """Return a JSON-serialisable status dict for the API endpoint."""
    if _scheduler is None or not _scheduler.running:
        return {"running": False, "jobs": []}

    jobs = []
    for job in _scheduler.get_jobs():
        next_run = job.next_run_time
        jobs.append({
            "id": job.id,
            "name": job.name,
            "next_run": next_run.isoformat() if next_run else None,
        })

    return {"running": True, "jobs": jobs}
