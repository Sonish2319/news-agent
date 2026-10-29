
import html
import logging
import smtplib
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

        parts.append(f"""
        <article style="margin-bottom:28px">
          <h2>{index}. {headline}</h2>
          <p><b>{category}</b> · Importance: {ranked.score}/10</p>
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


def send_email(
    stories: list[tuple[RankedStory, Story]],
    country: CountryChoice = "Nepal",
    email_to: str | None = None,
) -> None:
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
