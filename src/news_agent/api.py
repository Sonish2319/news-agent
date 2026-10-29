"""
FastAPI server for the News Agent.

POST /api/news  →  queues a background job and immediately returns 202.
GET  /api/health →  liveness check.
"""

import logging
import threading
from typing import Literal

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr, Field

from news_agent.logging_config import configure_logging
from news_agent.pipeline import run_pipeline

configure_logging()
logger = logging.getLogger(__name__)

app = FastAPI(
    title="News Agent API",
    version="1.0.0",
    description="AI-powered news briefing agent",
)

# Allow requests from the React dev server (port 5173) and any localhost port.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://localhost:3000",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

CountryChoice = Literal["Nepal", "India", "International"]


class NewsRequest(BaseModel):
    country: CountryChoice = Field(
        ...,
        description="Country to fetch news for",
    )
    email: EmailStr = Field(
        ...,
        description="Email address to deliver the briefing to",
    )
    top_stories: int = Field(
        default=5,
        ge=1,
        le=20,
        description="Number of top stories to include (1–20)",
    )


class NewsResponse(BaseModel):
    message: str
    run_id: str | None = None


def _run_agent_in_background(
    country: CountryChoice,
    email: str,
    top_stories: int,
) -> None:
    """Execute the full pipeline in a background thread."""
    try:
        logger.info(
            "Background job starting | country=%s | email=%s | top=%d",
            country, email, top_stories,
        )
        result = run_pipeline(
            country=country,
            email_to=email,
            top_stories=top_stories,
        )
        logger.info(
            "Background job finished | run_id=%s | stories=%d",
            result.run_id, result.selected_count,
        )
    except Exception:
        logger.exception(
            "Background job failed | country=%s | email=%s",
            country, email,
        )


@app.get("/api/health")
def health_check() -> dict:
    return {"status": "ok"}


@app.post("/api/news", status_code=202, response_model=NewsResponse)
def request_news(payload: NewsRequest) -> NewsResponse:
    """
    Accept a news briefing request and immediately return 202 Accepted.
    The agent runs in a background thread so Ollama's latency doesn't
    block the HTTP response.
    """
    logger.info(
        "Received request | country=%s | email=%s | top=%d",
        payload.country, payload.email, payload.top_stories,
    )

    thread = threading.Thread(
        target=_run_agent_in_background,
        args=(payload.country, payload.email, payload.top_stories),
        daemon=True,
        name=f"news-agent-{payload.country}-{payload.email[:6]}",
    )
    thread.start()

    return NewsResponse(
        message=(
            f"✅ Your request has been received! "
            f"The agent is collecting the top {payload.top_stories} "
            f"{payload.country} news stories and will email them to "
            f"{payload.email} shortly. "
            f"Since we use a local AI model, this may take a few minutes."
        )
    )
