"""
Yesterday-vs-today story comparison.

After ranking today's top stories this module looks up yesterday's briefing
history and annotates each :class:`~news_agent.models.RankedStory` with a
``trend`` value:

* ``"new"``      – story not seen in yesterday's briefing for this recipient.
* ``"ongoing"``  – story (same content hash) appeared in yesterday's briefing.
* ``"resolved"`` – not used here; reserved for future topic-level tracking.
"""

import logging
from datetime import datetime, timedelta, timezone

from news_agent.models import RankedStory, Story, Trend

logger = logging.getLogger(__name__)


def annotate_trends(
    briefing: list[tuple[RankedStory, Story]],
    recipient: str,
    window_hours: int = 28,
) -> list[tuple[RankedStory, Story]]:
    """Tag each story with a ``trend`` based on yesterday's briefing.

    Imports the DB helper lazily to keep this module independently testable.
    """
    from news_agent.storage.database import get_briefed_hashes

    yesterday_hashes = get_briefed_hashes(recipient, window_hours=window_hours)

    annotated: list[tuple[RankedStory, Story]] = []
    for ranked, original in briefing:
        if original.content_hash in yesterday_hashes:
            trend: Trend = "ongoing"
        else:
            trend = "new"

        updated = ranked.model_copy(update={"trend": trend})
        annotated.append((updated, original))

    new_count = sum(1 for r, _ in annotated if r.trend == "new")
    ongoing_count = sum(1 for r, _ in annotated if r.trend == "ongoing")
    logger.info(
        "Trend annotation: %d new, %d ongoing stories for %s",
        new_count, ongoing_count, recipient,
    )

    return annotated
