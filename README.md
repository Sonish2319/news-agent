# Daily News Agent

A local-first news briefing system. It collects stories from RSS feeds, removes
duplicates, asks a locally hosted Ollama model to select and summarize the most
important stories, then emails an HTML briefing to the requested recipient.
A React web app provides a simple way to request a briefing for Nepal, India, or
international news.

## Features

- **Country-specific coverage:** choose Nepal, India, or International. Each
  choice uses its own set of configured RSS sources.
- **RSS collection and cleanup:** fetches recent feed entries, normalizes URLs
  and titles, removes tracking parameters, and skips duplicate URLs and titles.
- **Persistent story and run data:** stores collected stories, pipeline run
  status, and successful email delivery records in SQLite.
- **AI-ranked briefings:** sends a limited set of story candidates to Ollama.
  The model returns ranked stories with a score, headline, summary, category,
  and an explanation of why each story matters. The result is schema-validated,
  checked against candidate IDs, and retried on failures.
- **Email delivery:** sends an HTML email with source links through Gmail SMTP.
- **Web request form:** select a region, provide a recipient email, and choose
  from 1 to 20 stories.
- **HTTP API:** accepts briefing requests asynchronously and exposes a health
  check and interactive API documentation.
- **Configurable operation:** model, feed limits, database location, timezone,
  and log level can be configured through environment variables.
- **Automated tests:** includes tests for deduplication, ranking, and pipeline
  behavior.

## How the system works

1. A request comes from the web form (`POST /api/news`) or the command-line
   entry point.
2. The backend fetches RSS feeds for the selected region and validates and
   normalizes the story data.
3. Duplicate stories are filtered, and stories are saved in SQLite.
4. Up to 40 candidates are sent to the configured Ollama model for structured
   ranking and summarization.
5. The selected stories are formatted as an HTML briefing and emailed through
   Gmail SMTP.
6. Run status and successful delivery records are stored in SQLite; failures
   are recorded in the run status and application logs.

The model runs locally through Ollama. RSS providers and Gmail are still
external services: feed requests go to the configured publishers, and the
briefing is sent through Gmail to the address supplied for the request.

## Requirements

- Python 3.11 or newer
- Node.js and npm (for the web app)
- [Ollama](https://ollama.com/) with the configured model available locally
- A Gmail account with an app password for SMTP delivery

## Setup

Run these commands from the `daily-news-agent` directory.

### 1. Configure environment variables

Create a `.env` file in this directory:

```dotenv
GMAIL_ADDRESS=your-sender@gmail.com
GMAIL_APP_PASSWORD=your-gmail-app-password
EMAIL_TO=your-default-recipient@example.com

# Optional settings; these are the application defaults.
OLLAMA_MODEL=qwen3:4b
OLLAMA_URL=http://localhost:11434
OLLAMA_TIMEOUT=800
TOP_STORIES=20
RSS_ENTRIES_PER_FEED=20
DATABASE_PATH=data/news.db
LOG_LEVEL=INFO
TIMEZONE_NAME=Asia/Kathmandu
```

The three Gmail/email settings are required, including when you submit a
recipient address through the web app. Keep `.env` private and do not commit
real credentials. `GMAIL_APP_PASSWORD` should be a Gmail app password, not
your regular account password.

The Ollama URL is the server base URL; the application appends `/api/chat`.
The model defaults to `qwen3:4b`.

### 2. Install and prepare the local model

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -e ".[dev]"
ollama pull qwen3:4b
```

Make sure the Ollama service is running before requesting a briefing.

### 3. Start the backend

For the API used by the web app:

```powershell
python start_api.py
```

The API listens on `http://localhost:8000`. Interactive API documentation is
available at `http://localhost:8000/docs`.

To run one briefing directly using `EMAIL_TO` from `.env` instead:

```powershell
python -m news_agent.main
```

### 4. Start the web app

In a second terminal, from the `daily-news-agent` directory:

```powershell
cd news-frontend
npm install
npm run dev
```

Open the Vite URL printed in the terminal (normally `http://localhost:5173`).
The frontend is configured to send requests to `http://localhost:8000`.

## API

### `POST /api/news`

Accepts a briefing request and returns `202 Accepted` while the pipeline runs
in a background thread.

```json
{
  "country": "Nepal",
  "email": "reader@example.com",
  "top_stories": 5
}
```

`country` must be `Nepal`, `India`, or `International`; `top_stories` must be
between 1 and 20. The response confirms that the request was accepted. The
current API does not provide a job-status polling endpoint; completion or
failure is recorded in the backend logs and database.

### `GET /api/health`

Returns `{"status": "ok"}` when the API process is responding.

## Configuration

| Variable | Required | Default | Description |
|---|---:|---|---|
| `GMAIL_ADDRESS` | Yes | — | Gmail sender address |
| `GMAIL_APP_PASSWORD` | Yes | — | Gmail app password used for SMTP |
| `EMAIL_TO` | Yes | — | Default recipient for command-line runs |
| `OLLAMA_MODEL` | No | `qwen3:4b` | Local Ollama model name |
| `OLLAMA_URL` | No | `http://localhost:11434` | Ollama server base URL |
| `OLLAMA_TIMEOUT` | No | `800` | Model request timeout in seconds |
| `TOP_STORIES` | No | `20` | Default number of stories (1–30) |
| `RSS_ENTRIES_PER_FEED` | No | `20` | Maximum entries read from each feed (1–100) |
| `DATABASE_PATH` | No | `data/news.db` | SQLite database path, relative to the process working directory unless absolute |
| `LOG_LEVEL` | No | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR`, or `CRITICAL` |
| `TIMEZONE_NAME` | No | `Asia/Kathmandu` | Timezone used for email dates |

The web API accepts at most 20 stories per request, even though the
command-line configuration permits a default up to 30.

## Development

Run the backend tests from the project directory:

```powershell
pytest
```

Build the frontend:

```powershell
cd news-frontend
npm run build
```

## Current scope

- Briefings are generated when requested; there is no built-in scheduler for
  automatic daily delivery.
- API requests run in a background thread in the API process. They are not a
  durable queue, and the current web interface does not show job completion
  status.
- AI summaries are generated from RSS-provided titles and summaries. Check the
  linked original reporting for context and verification.
