
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

        -- Persistent briefing history: records every story hash sent to a
        -- recipient so we never repeat the same story in a later briefing.
        CREATE TABLE IF NOT EXISTS briefing_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT NOT NULL REFERENCES runs(id),
            recipient TEXT NOT NULL,
            content_hash TEXT NOT NULL,
            briefed_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_stories_published
        ON stories(published_at);

        CREATE INDEX IF NOT EXISTS idx_runs_started
        ON runs(started_at);

        CREATE INDEX IF NOT EXISTS idx_briefing_history_recipient
        ON briefing_history(recipient, briefed_at);

        CREATE INDEX IF NOT EXISTS idx_briefing_history_hash
        ON briefing_history(content_hash);
        """)


# ── Story persistence ────────────────────────────────────────────────────────

def get_known_hashes(since: datetime | None = None) -> set[str]:
    """Return content hashes of stories already in the database.

    If *since* is provided, only hashes collected on or after that time are
    returned.  Pass ``None`` to get every stored hash (useful for unit tests).
    """
    with connect() as db:
        if since is None:
            rows = db.execute("SELECT content_hash FROM stories").fetchall()
        else:
            rows = db.execute(
                "SELECT content_hash FROM stories WHERE collected_at >= ?",
                (since.isoformat(),),
            ).fetchall()
    return {row["content_hash"] for row in rows}


def save_stories(stories: list[Story]) -> list[Story]:
    """Persist stories and return them with their database IDs.

    Stories whose *content_hash* is already in the DB are returned with
    ``is_new=False``; freshly inserted rows get ``is_new=True``.
    """
    saved: list[Story] = []

    with connect() as db:
        for story in stories:
            cursor = db.execute(
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

            # rowcount == 0  → row already existed (duplicate)
            is_new = cursor.rowcount > 0

            row = db.execute(
                "SELECT id FROM stories WHERE content_hash = ?",
                (story.content_hash,),
            ).fetchone()

            saved.append(story.model_copy(update={"id": row["id"], "is_new": is_new}))

    return saved


# ── Run lifecycle ────────────────────────────────────────────────────────────

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


# ── Delivery recording ───────────────────────────────────────────────────────

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


# ── Briefing history (prevent repeat emails) ─────────────────────────────────

def get_briefed_hashes(recipient: str, window_hours: int) -> set[str]:
    """Return content hashes sent to *recipient* within the last *window_hours*.

    Used by the pipeline to skip stories the user has already received.
    """
    from datetime import timedelta
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=window_hours)).isoformat()

    with connect() as db:
        rows = db.execute(
            """
            SELECT content_hash
            FROM briefing_history
            WHERE recipient = ? AND briefed_at >= ?
            """,
            (recipient, cutoff),
        ).fetchall()

    return {row["content_hash"] for row in rows}


def record_briefing_stories(
    run_id: str,
    recipient: str,
    content_hashes: list[str],
) -> None:
    """Persist the hashes of stories that were included in a sent briefing."""
    now = datetime.now(timezone.utc).isoformat()

    with connect() as db:
        db.executemany(
            """
            INSERT INTO briefing_history (run_id, recipient, content_hash, briefed_at)
            VALUES (?, ?, ?, ?)
            """,
            [(run_id, recipient, h, now) for h in content_hashes],
        )
