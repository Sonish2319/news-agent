
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from news_agent.config import get_settings
from news_agent.models import Story


def connect() -> sqlite3.Connection:
    settings = get_settings()
    path = settings.database_path
    path.parent.mkdir(parents=True, exist_ok=True)

    connection = sqlite3.connect(path, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 10000")
    return connection


def initialize_database() -> None:
    with connect() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS stories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            content_hash TEXT NOT NULL UNIQUE,
            title TEXT NOT NULL,
            summary TEXT NOT NULL DEFAULT '',
            source TEXT NOT NULL,
            url TEXT NOT NULL,
            published_at TEXT,
            collected_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS runs (
            id TEXT PRIMARY KEY,
            started_at TEXT NOT NULL,
            finished_at TEXT,
            status TEXT NOT NULL DEFAULT 'running',
            collected_count INTEGER NOT NULL DEFAULT 0,
            selected_count INTEGER NOT NULL DEFAULT 0,
            emailed INTEGER NOT NULL DEFAULT 0,
            error TEXT
        );

        CREATE TABLE IF NOT EXISTS deliveries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT NOT NULL REFERENCES runs(id),
            recipient TEXT NOT NULL,
            status TEXT NOT NULL,
            attempted_at TEXT NOT NULL,
            error TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_stories_published
        ON stories(published_at);

        CREATE INDEX IF NOT EXISTS idx_runs_started
        ON runs(started_at);
        """)


def save_stories(stories: list[Story]) -> list[Story]:
    """Persist stories and return them with their database IDs."""
    saved: list[Story] = []

    with connect() as db:
        for story in stories:
            db.execute(
                """
                INSERT INTO stories (
                    content_hash, title, summary, source, url,
                    published_at, collected_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(content_hash) DO NOTHING
                """,
                (
                    story.content_hash,
                    story.title,
                    story.summary,
                    story.source,
                    str(story.url),
                    story.published_at.isoformat()
                    if story.published_at else None,
                    story.collected_at.isoformat(),
                ),
            )

            row = db.execute(
                "SELECT id FROM stories WHERE content_hash = ?",
                (story.content_hash,),
            ).fetchone()

            saved.append(story.model_copy(update={"id": row["id"]}))

    return saved


def start_run(run_id: str) -> None:
    with connect() as db:
        db.execute(
            """
            INSERT INTO runs (id, started_at, status)
            VALUES (?, ?, 'running')
            """,
            (run_id, datetime.now(timezone.utc).isoformat()),
        )


def finish_run(
    run_id: str,
    *,
    status: str,
    collected_count: int,
    selected_count: int,
    emailed: bool,
    error: str | None = None,
) -> None:
    if status not in {"success", "partial", "failed"}:
        raise ValueError(f"Invalid run status: {status}")

    with connect() as db:
        db.execute(
            """
            UPDATE runs
            SET finished_at = ?,
                status = ?,
                collected_count = ?,
                selected_count = ?,
                emailed = ?,
                error = ?
            WHERE id = ?
            """,
            (
                datetime.now(timezone.utc).isoformat(),
                status,
                collected_count,
                selected_count,
                int(emailed),
                error[:2000] if error else None,
                run_id,
            ),
        )


def record_delivery(
    run_id: str,
    recipient: str,
    *,
    status: str,
    error: str | None = None,
) -> None:
    if status not in {"sent", "failed"}:
        raise ValueError(f"Invalid delivery status: {status}")

    with connect() as db:
        db.execute(
            """
            INSERT INTO deliveries (
                run_id, recipient, status, attempted_at, error
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                run_id,
                recipient,
                status,
                datetime.now(timezone.utc).isoformat(),
                error[:2000] if error else None,
            ),
        )
