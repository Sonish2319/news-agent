"""
Event clustering for the news pipeline.

Groups incoming stories by topic similarity so that duplicate events from
different sources are consolidated.  One representative story (highest score
from ranking, or earliest collected) is kept per cluster.
"""

import logging
from difflib import SequenceMatcher

from news_agent.models import Story
from news_agent.sources.rss import normalize_title

logger = logging.getLogger(__name__)

# Two stories are merged into the same cluster when their normalised titles
# are at least this similar.
_DEFAULT_THRESHOLD = 0.72


def _similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


def cluster_stories(
    stories: list[Story],
    threshold: float = _DEFAULT_THRESHOLD,
) -> list[Story]:
    """Return one representative story per event cluster.

    Stories are compared by normalised title.  When two titles exceed
    *threshold* similarity they are merged; the first-seen story wins
    (preserving the original source and URL).

    This runs *after* exact-duplicate removal by
    :func:`~news_agent.processing.deduplication.deduplicate_stories` and
    *before* ranking, so Ollama sees a compact, event-distinct candidate list.
    """
    if not stories:
        return []

    cluster_titles: list[str] = []
    representatives: list[Story] = []

    for story in stories:
        norm = normalize_title(story.title)

        matched = False
        for existing in cluster_titles:
            if _similarity(norm, existing) >= threshold:
                matched = True
                break

        if not matched:
            cluster_titles.append(norm)
            representatives.append(story)

    logger.info(
        "Clustering: %d stories → %d event clusters (threshold=%.2f)",
        len(stories), len(representatives), threshold,
    )

    return representatives
