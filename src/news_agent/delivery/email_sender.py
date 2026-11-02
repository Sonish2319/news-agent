
import html
import logging
import smtplib
import time
from datetime import datetime
from email.message import EmailMessage
from email.utils import formatdate
from typing import Literal

from news_agent.config import get_settings
from news_agent.models import RankedStory, Story

logger = logging.getLogger(__name__)

CountryChoice = Literal["Nepal", "India", "International"]

COUNTRY_LABELS = {
    "Nepal": "Nepal",
    "India": "India",
    "International": "International",
}

_TREND_BADGE = {
    "new":      "🆕 New",
    "ongoing":  "🔄 Ongoing",
    "resolved": "✅ Resolved",
}


def build_html(
    stories: list[tuple[RankedStory, Story]],
    country: CountryChoice = "Nepal",
    email_to: str | None = None,
) -> str:
    settings = get_settings()
    now = datetime.now(settings.timezone)
    country_label = COUNTRY_LABELS.get(country, country)

    parts = [
        "<html><body style='font-family:Arial,sans-serif;"
        "max-width:760px;margin:auto;line-height:1.6'>",
        f"<h1>Daily News Briefing — {html.escape(country_label)}</h1>",
        f"<p>{html.escape(now.strftime('%A, %d %B %Y'))}</p>",
        "<hr>",
    ]

    for index, (ranked, original) in enumerate(stories, 1):
        headline = html.escape(ranked.headline)
        summary = html.escape(ranked.summary)
        why = html.escape(ranked.why_it_matters)
        category = html.escape(ranked.category)
        source = html.escape(original.source)
        url = html.escape(str(original.url), quote=True)
        trend_badge = _TREND_BADGE.get(ranked.trend, "")

        # 🆕 badge shown when the story is freshly collected this run.
        new_badge = " <span style='color:#0a84ff;font-size:0.8em'>🆕 Just In</span>" \
            if original.is_new else ""

        parts.append(f"""
        <article style="margin-bottom:28px">
          <h2>{index}. {headline}{new_badge}</h2>
          <p><b>{category}</b> · Importance: {ranked.score}/10
             &nbsp;|&nbsp; <span style="color:#666;font-size:0.9em">{trend_badge}</span>
          </p>
          <p>{summary}</p>
          <p><b>Why it matters:</b> {why}</p>
          <p><a href="{url}">Read original report — {source}</a></p>
        </article>
        """)

    if not stories:
        parts.append("<p>No usable stories were selected.</p>")

    parts.append(
        "<hr><p>Generated locally with Ollama. "
        "Summaries are AI-generated; consult original reports.</p>"
        "</body></html>"
    )

    return "\n".join(parts)


class SmtpDeliveryError(OSError):
    """Raised when all SMTP delivery attempts have been exhausted."""


def send_email(
    stories: list[tuple[RankedStory, Story]],
    country: CountryChoice = "Nepal",
    email_to: str | None = None,
) -> None:
    """Send the briefing via Gmail SMTP with exponential-backoff retry.

    Raises :class:`SmtpDeliveryError` if all attempts fail so that the caller
    can record the failure before re-raising.
    """
    settings = get_settings()
    now = datetime.now(settings.timezone)
    country_label = COUNTRY_LABELS.get(country, country)

    recipient = email_to or settings.email_to

    msg = EmailMessage()
    msg["Subject"] = (
        f"Daily News Briefing ({country_label}) — {now:%d %b %Y}"
    )
    msg["From"] = settings.gmail_address
    msg["To"] = recipient
    msg["Date"] = formatdate(localtime=True)

    msg.set_content(
        "Your email client does not support HTML. "
        "Please view this message in an HTML-capable client."
    )
    msg.add_alternative(
        build_html(stories, country=country, email_to=email_to),
        subtype="html",
    )

    max_retries = settings.smtp_max_retries
    last_error: Exception | None = None

    for attempt in range(max_retries + 1):
        try:
            with smtplib.SMTP(
                "smtp.gmail.com", 587, timeout=30
            ) as smtp:
                smtp.ehlo()
                smtp.starttls()
                smtp.ehlo()
                smtp.login(
                    settings.gmail_address,
                    settings.gmail_app_password.get_secret_value(),
                )
                smtp.send_message(msg)

            logger.info("Briefing delivered to %s", recipient)
            return

        except (smtplib.SMTPException, OSError, TimeoutError) as exc:
            last_error = exc
            logger.warning(
                "SMTP attempt %d/%d failed for %s: %s",
                attempt + 1, max_retries + 1, recipient, exc,
            )

            if attempt < max_retries:
                delay = 5 * (2 ** attempt)   # 5s, 10s, 20s …
                logger.info("Retrying SMTP in %ds …", delay)
                time.sleep(delay)

    raise SmtpDeliveryError(
        f"SMTP delivery to {recipient} failed after {max_retries + 1} attempts"
    ) from last_error


def build_breaking_news_html(
    stories: list[tuple[RankedStory, Story]],
    country: CountryChoice = "Nepal",
) -> str:
    """Build a compact HTML email for breaking-news alert emails."""
    settings = get_settings()
    now = datetime.now(settings.timezone)
    country_label = COUNTRY_LABELS.get(country, country)

    parts = [
        "<html><body style='font-family:Arial,sans-serif;"
        "max-width:760px;margin:auto;line-height:1.6'>",
        "<h1>⚡ Breaking News Alert</h1>",
        f"<p><b>{html.escape(country_label)}</b> · "
        f"{html.escape(now.strftime('%A, %d %B %Y · %H:%M'))}</p>",
        "<hr>",
    ]

    for index, (ranked, original) in enumerate(stories, 1):
        headline = html.escape(ranked.headline)
        summary = html.escape(ranked.summary)
        source = html.escape(original.source)
        url = html.escape(str(original.url), quote=True)

        parts.append(f"""
        <article style="margin-bottom:20px">
          <h2>⚡ {index}. {headline}</h2>
          <p>Importance: {ranked.score}/10</p>
          <p>{summary}</p>
          <p><a href="{url}">Read original report — {source}</a></p>
        </article>
        """)

    if not stories:
        parts.append("<p>No high-priority breaking stories at this time.</p>")

    parts.append(
        "<hr><p>Breaking-news alert generated by your local news agent.</p>"
        "</body></html>"
    )

    return "\n".join(parts)


def send_breaking_news_email(
    stories: list[tuple[RankedStory, Story]],
    country: CountryChoice = "Nepal",
    email_to: str | None = None,
) -> None:
    """Send a breaking-news alert email."""
    settings = get_settings()
    now = datetime.now(settings.timezone)
    country_label = COUNTRY_LABELS.get(country, country)
    recipient = email_to or settings.email_to

    msg = EmailMessage()
    msg["Subject"] = (
        f"⚡ Breaking News Alert ({country_label}) — {now:%d %b %Y %H:%M}"
    )
    msg["From"] = settings.gmail_address
    msg["To"] = recipient
    msg["Date"] = formatdate(localtime=True)

    msg.set_content(
        "Breaking news alert — please view in an HTML-capable email client."
    )
    msg.add_alternative(
        build_breaking_news_html(stories, country=country),
        subtype="html",
    )

    with smtplib.SMTP("smtp.gmail.com", 587, timeout=30) as smtp:
        smtp.ehlo()
        smtp.starttls()
        smtp.ehlo()
        smtp.login(
            settings.gmail_address,
            settings.gmail_app_password.get_secret_value(),
        )
        smtp.send_message(msg)

    logger.info("Breaking-news alert delivered to %s", recipient)
