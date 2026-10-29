
import hashlib
import logging
import re
import unicodedata
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from time import struct_time
from typing import Literal
from urllib.parse import (
    parse_qsl,
    urlencode,
    urlsplit,
    urlunsplit,
)

import feedparser
import requests

from news_agent.config import get_settings
from news_agent.models import Story

logger = logging.getLogger(__name__)

CountryChoice = Literal["Nepal", "India", "International"]

# ── Feed groups by country ──────────────────────────────────────────────────

FEEDS_NEPAL: dict[str, str] = {
    "The Kathmandu Post":  "https://kathmandupost.com/rss",
    "OnlineKhabar English": "https://english.onlinekhabar.com/feed/",
    "The Himalayan Times":  "https://thehimalayantimes.com/feed/",
    "Nepali Times":         "https://www.nepalitimes.com/feed/",
    "Ratopati English":     "http://english.ratopati.com/rss/",
    "Lokaantar English":    "http://english.lokaantar.com/feed/",
    "Kathmandu Tribune":    "http://kathmandutribune.com/feed/",
    "Setopati English":     "https://en.setopati.com/feed",
    "Setopati Nepali":      "https://www.setopati.com/feed/",
    # Also include BBC World for international context
    "BBC World":            "https://feeds.bbci.co.uk/news/world/rss.xml",
}

FEEDS_INDIA: dict[str, str] = {
    "Indian Express India":  "https://indianexpress.com/section/india/feed/",
    "Indian Express World":  "https://indianexpress.com/section/world/feed/",
    "The Hindu National":    "https://www.thehindu.com/news/national/feeder/default.rss",
    "NDTV Top Stories":      "https://feeds.feedburner.com/ndtvnews-top-stories",
    "NDTV Latest":           "https://feeds.feedburner.com/ndtvnews-latest",
    "Hindustan Times India": "https://www.hindustantimes.com/feeds/rss/india-news/rssfeed.xml",
    "News18 India":          "https://www.news18.com/rss/india.xml",
    "India Today":           "https://www.indiatoday.in/rss/1206577",
    "Mint News":             "https://www.livemint.com/rss/news",
    "Business Standard":     "https://www.business-standard.com/rss/latest.rss",
    "Economic Times":        "https://economictimes.indiatimes.com/rssfeedstopstories.cms",
    "PIB India":             "https://pib.gov.in/RssMain.aspx?ModId=6&Lang=1&Regid=1",
}

FEEDS_INTERNATIONAL: dict[str, str] = {
    "BBC World":      "https://feeds.bbci.co.uk/news/world/rss.xml",
    "BBC Business":   "https://feeds.bbci.co.uk/news/business/rss.xml",
    "BBC Technology": "https://feeds.bbci.co.uk/news/technology/rss.xml",
    "NPR":            "https://feeds.npr.org/1004/rss.xml",
    "Al Jazeera":     "https://www.aljazeera.com/xml/rss/all.xml",
}

COUNTRY_FEEDS: dict[str, dict[str, str]] = {
    "Nepal":         FEEDS_NEPAL,
    "India":         FEEDS_INDIA,
    "International": FEEDS_INTERNATIONAL,
}

TRACKING_PARAMS = {
    "fbclid", "gclid", "mc_cid", "mc_eid",
    "ref", "source",
}


def normalize_url(url: str) -> str:
    """Remove common tracking parameters and URL fragments."""
    parts = urlsplit(url.strip())

    query = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if not key.lower().startswith("utm_")
        and key.lower() not in TRACKING_PARAMS
    ]

    return urlunsplit((
        parts.scheme.lower(),
        parts.netloc.lower(),
        parts.path.rstrip("/") or "/",
        urlencode(query),
        "",
    ))


def normalize_title(title: str) -> str:
    """Normalize titles for exact-title deduplication."""
    title = unicodedata.normalize("NFKC", title).casefold()
    return re.sub(r"\W+", " ", title).strip()


def make_content_hash(url: str) -> str:
    normalized = normalize_url(url)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def clean_summary(value: str, limit: int = 2000) -> str:
    value = re.sub(r"<[^>]*>", " ", value or "")
    value = re.sub(r"\s+", " ", value)
    return value.strip()[:limit]


def parse_published(entry) -> datetime | None:
    """Convert an RSS publication timestamp to aware UTC."""
    published = entry.get("published_parsed")

    if isinstance(published, struct_time):
        return datetime(*published[:6], tzinfo=timezone.utc)

    raw = entry.get("published") or entry.get("updated")
    if raw:
        try:
            parsed = parsedate_to_datetime(raw)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)
        except (TypeError, ValueError, OverflowError):
            pass

    return None


def collect_news(country: CountryChoice = "Nepal") -> list[Story]:
    """Fetch RSS stories for the given country."""
    settings = get_settings()
    collected_at = datetime.now(timezone.utc)

    feeds = COUNTRY_FEEDS.get(country, FEEDS_NEPAL)

    session = requests.Session()
    session.headers.update({
        "User-Agent": "PersonalNewsAgent/2.0 (+RSS reader)"
    })

    stories: list[Story] = []
    seen_urls: set[str] = set()
    seen_titles: set[str] = set()

    try:
        for source, feed_url in feeds.items():
            try:
                response = session.get(feed_url, timeout=(5, 20))
                response.raise_for_status()

                # Avoid parsing an unexpectedly large response.
                if len(response.content) > 5_000_000:
                    logger.warning("Feed too large, skipping %s", source)
                    continue

                feed = feedparser.parse(response.content)

                if feed.bozo and not feed.entries:
                    logger.warning("Invalid feed: %s", source)
                    continue

                count = 0

                for entry in feed.entries[:settings.rss_entries_per_feed]:
                    title = clean_summary(entry.get("title", ""), 300)
                    link = entry.get("link", "").strip()

                    if not title or not link:
                        continue

                    try:
                        normalized_url = normalize_url(link)
                        story_url = normalized_url
                        title_key = normalize_title(title)

                        if (
                            normalized_url in seen_urls
                            or title_key in seen_titles
                        ):
                            continue

                        story = Story(
                            title=title,
                            summary=clean_summary(
                                entry.get("summary", "")
                            ),
                            source=source,
                            url=story_url,
                            published_at=parse_published(entry),
                            collected_at=collected_at,
                            content_hash=make_content_hash(story_url),
                        )
                    except (ValueError, TypeError) as exc:
                        logger.debug(
                            "Skipping invalid entry from %s: %s",
                            source, exc,
                        )
                        continue

                    seen_urls.add(normalized_url)
                    seen_titles.add(title_key)
                    stories.append(story)
                    count += 1

                logger.info("%s: collected %d stories", source, count)

            except requests.RequestException:
                logger.exception("Could not fetch feed: %s", source)

    finally:
        session.close()

    logger.info(
        "Collected %d unique RSS stories for %s",
        len(stories), country,
    )
    return stories
