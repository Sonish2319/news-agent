
import logging
from typing import Literal
from uuid import uuid4

from news_agent.config import get_settings
from news_agent.delivery.email_sender import SmtpDeliveryError, send_email
from news_agent.models import RunResult, Story
from news_agent.processing.clustering import cluster_stories
from news_agent.processing.comparison import annotate_trends
from news_agent.processing.deduplication import deduplicate_stories
from news_agent.processing.ranking import rank_stories
from news_agent.sources.rss import collect_news
from news_agent.storage.database import (
    finish_run,
    get_briefed_hashes,
    initialize_database,
    record_briefing_stories,
    record_delivery,
    save_stories,
    start_run,
)

logger = logging.getLogger(__name__)

CountryChoice = Literal["Nepal", "India", "International"]


def run_pipeline(
    country: CountryChoice = "Nepal",
    email_to: str | None = None,
    top_stories: int | None = None,
) -> RunResult:
    settings = get_settings()
    run_id = str(uuid4())

    collected_count = 0
    selected_count = 0
    emailed = False
    run_status = "failed"

    recipient = email_to or settings.email_to

    initialize_database()
    start_run(run_id)

    try:
        # ── 1. Collect ──────────────────────────────────────────────────────
        collected = collect_news(country=country)
        collected_count = len(collected)

        if not collected:
            raise RuntimeError("No RSS stories could be collected.")

        # ── 2. Deduplicate within this batch ────────────────────────────────
        unique = deduplicate_stories(collected)

        # ── 3. Persist & tag new vs. previously-stored ──────────────────────
        persisted = save_stories(unique)

        new_count = sum(1 for s in persisted if s.is_new)
        logger.info(
            "Collected %d stories; %d after dedup; %d brand-new to the DB",
            collected_count, len(persisted), new_count,
        )

        # ── 4. Event clustering ─────────────────────────────────────────────
        clustered = cluster_stories(persisted)

        # ── 5. Filter out stories already briefed to this recipient ─────────
        briefed_hashes = get_briefed_hashes(
            recipient, window_hours=settings.briefing_dedup_hours
        )
        fresh = [s for s in clustered if s.content_hash not in briefed_hashes]

        logger.info(
            "Briefing history filter: %d stories removed (%d remain) for %s",
            len(clustered) - len(fresh), len(fresh), recipient,
        )

        # Fall back to all clustered stories if the fresh list is too small.
        requested_count = top_stories if top_stories is not None else settings.top_stories
        candidates = fresh if len(fresh) >= requested_count else clustered

        # ── 6. Rank ─────────────────────────────────────────────────────────
        ranked = rank_stories(
            candidates,
            country=country,
            top_stories=top_stories,
        )

        briefing: list[tuple] = [
            (item, candidates[item.id])
            for item in ranked
        ]
        selected_count = len(briefing)

        if not briefing:
            raise RuntimeError("No valid stories returned by Ollama.")

        # ── 7. Yesterday-vs-today trend annotation ──────────────────────────
        briefing = annotate_trends(briefing, recipient=recipient)

        # ── 8. Send email (with SMTP retry built into send_email) ────────────
        try:
            send_email(briefing, country=country, email_to=email_to)
            emailed = True
            run_status = "success"

            record_delivery(run_id, recipient, status="sent")

            # Persist which stories were included so future runs can skip them.
            sent_hashes = [original.content_hash for _, original in briefing]
            record_briefing_stories(run_id, recipient, sent_hashes)

        except SmtpDeliveryError as smtp_err:
            # All SMTP retries exhausted — record the failure but don't crash
            # the whole run so the DB still captures the collected/ranked data.
            logger.error(
                "SMTP delivery failed permanently for %s: %s",
                recipient, smtp_err,
            )
            record_delivery(
                run_id, recipient,
                status="failed",
                error=str(smtp_err),
            )
            run_status = "partial"
            raise

        result = RunResult(
            run_id=run_id,
            status=run_status,
            collected_count=collected_count,
            selected_count=selected_count,
            emailed=emailed,
        )

        finish_run(
            run_id,
            status=run_status,
            collected_count=collected_count,
            selected_count=selected_count,
            emailed=emailed,
        )

        logger.info(
            "Run %s succeeded: %d stories emailed to %s",
            run_id, selected_count, recipient,
        )
        return result

    except Exception as exc:
        logger.exception("Run %s failed", run_id)

        try:
            finish_run(
                run_id,
                status=run_status,
                collected_count=collected_count,
                selected_count=selected_count,
                emailed=emailed,
                error=str(exc),
            )
        except Exception:
            logger.exception("Could not persist failure status")

        raise
