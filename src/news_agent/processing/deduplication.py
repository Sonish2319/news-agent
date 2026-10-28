
from difflib import SequenceMatcher

from news_agent.models import Story
from news_agent.sources.rss import normalize_title, normalize_url


def deduplicate_stories(
    stories: list[Story],
    similarity_threshold: float = 0.92,
) -> list[Story]:
    """Remove exact duplicates and highly similar titles.

    Keep the first occurrence, preserving the original source and URL.
    """
    result: list[Story] = []
    seen_urls: set[str] = set()
    seen_titles: list[str] = []

    for story in stories:
        url = normalize_url(str(story.url))
        title = normalize_title(story.title)

        if not title or url in seen_urls:
            continue

        if any(
            title == previous
            or SequenceMatcher(None, title, previous).ratio()
            >= similarity_threshold
            for previous in seen_titles
        ):
            continue

        seen_urls.add(url)
        seen_titles.append(title)
        result.append(story)

    return result
