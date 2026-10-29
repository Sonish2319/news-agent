
import logging
from typing import Literal
from uuid import uuid4

from news_agent.config import get_settings
from news_agent.delivery.email_sender import send_email
from news_agent.models import RunResult, Story
from news_agent.processing.deduplication import deduplicate_stories
from news_agent.processing.ranking import rank_stories
from news_agent.sources.rss import collect_news
from news_agent.storage.database import (
    finish_run,
    initialize_database,
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

    recipient = email_to or settings.email_to

    initialize_database()
    start_run(run_id)

    try:
        collected = collect_news(country=country)
        collected_count = len(collected)

        if not collected:
            raise RuntimeError("No RSS stories could be collected.")

        unique = deduplicate_stories(collected)
        persisted = save_stories(unique)

        logger.info(
            "Collected %d stories; %d remain after deduplication",
            collected_count, len(persisted),
        )

        ranked = rank_stories(
            persisted,
            country=country,
            top_stories=top_stories,
        )

        # Candidate IDs are list indexes, not SQLite IDs.
        briefing = [
            (item, persisted[item.id])
            for item in ranked
        ]
        selected_count = len(briefing)

        if not briefing:
            raise RuntimeError("No valid stories returned by Ollama.")

        send_email(briefing, country=country, email_to=email_to)
        emailed = True

        record_delivery(
            run_id, recipient, status="sent"
        )

        result = RunResult(
            run_id=run_id,
            status="success",
            collected_count=collected_count,
            selected_count=selected_count,
            emailed=True,
        )

        finish_run(
            run_id,
            status=result.status,
            collected_count=collected_count,
            selected_count=selected_count,
            emailed=True,
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
                status="failed",
                collected_count=collected_count,
                selected_count=selected_count,
                emailed=emailed,
                error=str(exc),
            )
        except Exception:
            logger.exception("Could not persist failure status")

        raise
