
from datetime import datetime, timezone

from news_agent.models import Story
from news_agent.processing.deduplication import deduplicate_stories


def make_story(title: str, url: str) -> Story:
    return Story(
        title=title,
        summary="Test summary",
        source="Test",
        url=url,
        collected_at=datetime.now(timezone.utc),
        content_hash=f"hash-{url}",
    )


def test_removes_duplicate_urls():
    stories = [
        make_story("First headline", "https://example.com/story"),
        make_story("Different headline", "https://example.com/story"),
    ]

    assert len(deduplicate_stories(stories)) == 1


def test_removes_similar_titles():
    stories = [
        make_story(
            "Major earthquake strikes Nepal",
            "https://example.com/1",
        ),
        make_story(
            "Major earthquake strikes Nepal!",
            "https://example.com/2",
        ),
    ]

    assert len(deduplicate_stories(stories)) == 1


def test_keeps_distinct_stories():
    stories = [
        make_story("Major earthquake in Nepal", "https://example.com/1"),
        make_story("Central bank changes interest rates", "https://example.com/2"),
    ]

    assert len(deduplicate_stories(stories)) == 2
