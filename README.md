# JobSpy

An automated job-search pipeline that scrapes listings from LinkedIn and Seek, scores them against a personal profile using LLM-based multi-stage classification, and sends Telegram alerts for high-relevance matches.

## Why This Exists

Manually checking job boards is time-consuming and easy to miss postings. This project automates the full cycle: periodic scraping → deduplication → AI-powered relevance scoring → push notification, letting you focus on applying rather than searching.

## Architecture

The system is composed of independent services that communicate through a shared SQLite database and internal HTTP APIs.

```
┌──────────────┐   ┌──────────────┐
│ jobspy_scraper│   │ seek_scraper │
│  (LinkedIn)  │   │  (Seek.com.au)│
└──────┬───────┘   └──────┬───────┘
       │  writes           │  writes
       ▼                   ▼
┌──────────────┐   ┌──────────────┐
│   jobs.db    │   │ seek_jobs.db │
│  (SQLite)    │   │  (SQLite/PG) │
└──────┬───────┘   └──────┬───────┘
       │  reads            │  reads
       ▼                   ▼
┌──────────────┐   ┌──────────────┐
│  jobspy_api  │   │   seek_api   │
│  (FastAPI)   │   │  (FastAPI)   │
└──────┬───────┘   └──────┬───────┘
       │                   │
       └───────┬───────────┘
               ▼
       ┌───────────────┐
       │  aggregator   │
       │  (FastAPI)    │  ← AI relevance scoring (Groq)
       └───────┬───────┘
               │
       ┌───────┴───────┐
       │               │
       ▼               ▼
┌────────────┐  ┌────────────┐
│ flask_app  │  │  matcher   │
│ (dashboard)│  │(AI stages) │
└────────────┘  └─────┬──────┘
                      │
                      ▼
               ┌────────────┐
               │  Telegram   │
               │  alerts     │
               └────────────┘
```

### Services

| Service | Purpose | Port |
|---|---|---|
| **jobspy_scraper** | Scrapes LinkedIn via [python-jobspy](https://github.com/Bunsly/JobSpy), stores raw JSON payloads into SQLite. Runs on a cron schedule (hourly) or as a one-shot. | — |
| **seek_scraper** | Scrapes Seek.com.au IT listings via Scrapy with configurable weekday/weekend schedules, optional AI post-processing and backfill. | — |
| **matcher** | Three-stage AI pipeline: language filter → IT-role classifier → profile-fit scorer. Sends Telegram alerts for high-scoring matches. | — |
| **jobspy_api** | Read-only FastAPI over the LinkedIn scraper's `raw_jobs` table. | 6060 |
| **seek_api** | Read-only FastAPI over Seek job listings. Supports both SQLite and PostgreSQL backends. | 6059 |
| **aggregator_service** | Pulls from both APIs, deduplicates by URL, applies AI relevance scoring, and exposes a unified job listing with profile management. | 6061 |
| **flask_app** | Web dashboard for reviewing scraped jobs, AI decisions, and pipeline status. | 5000 |

## Technology Stack

| Layer | Technologies |
|---|---|
| Language | Python 3.11 / 3.12 |
| Scraping | [python-jobspy](https://github.com/Bunsly/JobSpy) ≥1.1.82, Scrapy 2.8 |
| AI / LLM | Groq API (Llama 3.1 8B for Stage 1, Llama 3.3 70B for Stage 2) |
| APIs | FastAPI ≥0.109, Uvicorn |
| Dashboard | Flask, Jinja2 templates |
| Database | SQLite (WAL mode) as primary; PostgreSQL optional for Seek |
| Scheduling | APScheduler (cron and interval triggers) |
| Notifications | Telegram Bot API |
| Containerisation | Docker, Docker Compose |
| CI/CD | GitHub Actions (self-hosted runner), Dependabot |
| Language detection | fast-langdetect |

## Matcher Pipeline Detail

The matcher processes jobs through three sequential stages:

1. **Stage 0 — Language filter**: Uses `fast-langdetect` to identify the description language. Jobs detected as German (≥90% confidence by default) are excluded. Configurable via `language_filter` in `config.yaml`.

2. **Stage 1 — IT-role classification**: Sends job titles in batched requests to a fast LLM (`llama-3.1-8b-instant`). Each title is classified as IT/non-IT with a confidence score. Non-IT titles with high confidence are excluded immediately.

3. **Stage 2 — Profile scoring**: Each remaining job is individually scored (0–100) against your profile summary by a larger LLM (`llama-3.3-70b-versatile`). Returns `include` (≥75), `maybe` (≥55), or `exclude` labels with reasons, fit factors, and anti-fit factors.

Jobs scoring ≥80 trigger a Telegram notification with title, company, score, and a direct link.

### Rate Limiting

Both matcher and aggregator implement client-side rate limiting that respects Groq's RPM/TPM quotas. Token usage is estimated before each request, reserved against the budget, and corrected after actual usage is reported. Exponential backoff with jitter handles 429 responses.

## Prerequisites

- Python 3.11+ (3.12 used in primary Dockerfile)
- Docker and Docker Compose (for containerised deployment)
- A [Groq API key](https://console.groq.com/) (required for matcher and aggregator AI features)
- A Telegram bot token and chat ID (required for notifications)

## Project Structure

```
.
├── config.yaml                  # Central YAML config (scraper + matcher)
├── Dockerfile                   # Multi-service image (scraper, matcher, flask, jobspy_api)
├── docker-compose.flask.yml     # Standalone Flask development compose
├── infra/
│   ├── docker-compose.yml       # Production compose (all services)
│   ├── docker-compose.override.yml  # Local development overrides
│   ├── migrate.py               # SQL migration runner
│   └── migrations/              # Versioned SQL schema files (0001–0006)
├── jobspy_scraper/              # LinkedIn scraper service
├── matcher/                     # AI classification pipeline
├── flask_app/                   # Web dashboard
├── jobspy_api/                  # Read-only API for LinkedIn jobs
├── seek_scraper/                # Seek.com.au scraper + scheduler
├── seek_api/                    # Read-only API for Seek jobs
├── aggregator_service/          # Unified aggregator with AI scoring
├── data/                        # Runtime SQLite databases (gitignored)
└── .github/
    ├── workflows/deploy.yml     # CI/CD: build + deploy on push to main
    ├── dependabot.yml           # Automated dependency updates
    └── copilot-instructions.md  # Project guidelines for AI tools
```

## Getting Started

### 1. Clone and Configure

```bash
git clone <repository-url>
cd JobSpy
```

Copy and edit the configuration:

```bash
# Central config for scraper and matcher
cp config.yaml config.yaml  # Edit search_terms, locations, thresholds, profile

# Seek scraper environment (if using Seek services)
cp seek_scraper/.env.example seek_scraper/.env
```

Edit `config.yaml` to set your search terms, locations, and profile summary:

```yaml
scraper:
  search_terms: ["software engineer", "software developer"]
  locations: ["Melbourne, Victoria, Australia"]
  hours_old: 12
  results_wanted: 200

matcher:
  profile:
    summary: >
      Your skills and preferences here.
  thresholds:
    include: 75
    maybe: 55
    min_score_to_alert: 80
```

### 2. Set Environment Variables

Create `infra/.env` with the required secrets:

```bash
GROQ_API_KEY=your_groq_api_key
TELEGRAM_BOT_TOKEN=your_telegram_bot_token
TELEGRAM_CHAT_ID=your_telegram_chat_id

# Optional
HTTP_PROXY=
HTTPS_PROXY=

# Required for Seek services
SEEK_DATABASE_ENGINE=sqlite
SEEK_DATABASE_TABLE=seek_jobs
```

> **Warning**: Never commit `.env` files. They are listed in `.gitignore`.

### 3. Deploy with Docker Compose (Recommended)

```bash
cd infra
docker compose build
docker compose up -d
```

This starts all services: migration → scraper → matcher → APIs → aggregator → dashboard.

> **Warning**: `docker compose down -v` will remove named volumes and **permanently delete** all scraped data. Use `docker compose down` (without `-v`) to stop services while preserving data.

Verify:

```bash
# Dashboard
curl http://127.0.0.1:5000

# JobSpy API
curl http://127.0.0.1:6060/health

# Seek API
curl http://127.0.0.1:6059/health

# Aggregator API
curl http://127.0.0.1:6061/api/v1/health
```

### 4. Run Locally (Without Docker)

#### Database Setup

Run migrations first to create the schema:

```bash
python infra/migrate.py
```

This applies all SQL files in `infra/migrations/` sequentially and tracks them in a `schema_migrations` table.

#### Scraper

```bash
pip install -r jobspy_scraper/requirements.txt

# One-shot scrape
python -m jobspy_scraper.main run --config config.yaml

# Scheduled (hourly at :00)
python -m jobspy_scraper.main serve --config config.yaml
```

#### Matcher

```bash
pip install -r matcher/requirements.txt

# Requires GROQ_API_KEY in environment
export GROQ_API_KEY=your_key
export TELEGRAM_BOT_TOKEN=your_token
export TELEGRAM_CHAT_ID=your_chat_id

python matcher/main.py
```

The matcher runs in an infinite loop, processing new jobs through all three stages, then sleeping for `sleep_seconds_when_idle` (default: 30s) when no work remains.

#### APIs

```bash
# JobSpy API
pip install -r jobspy_api/requirements.txt
uvicorn jobspy_api.main:app --reload --port 8000

# Seek API (requires DATABASE_ENGINE env var)
pip install -r seek_api/requirements.txt
export DATABASE_ENGINE=sqlite
export SQLITE_DB_PATH=./data/seek_jobs.sqlite3
export DATABASE_TABLE=seek_jobs
uvicorn seek_api.main:app --reload --port 8001

# Aggregator
pip install -r aggregator_service/requirements.txt
python -m aggregator_service.migrate
uvicorn aggregator_service.main:app --reload --port 8010
```

#### Dashboard

```bash
pip install -r flask_app/requirements.txt
python flask_app/app.py
```

> **Note**: The Flask app connects to `/app/data/jobs.db` by default (a Docker path). When running outside Docker, ensure the database exists at `data/jobs.db` relative to the project root, or modify the path in `flask_app/app.py`.

## Configuration Reference

### `config.yaml` — Scraper Section

| Key | Type | Default | Description |
|---|---|---|---|
| `sqlite_path` | string | `./data/jobs.db` | Path to the SQLite database |
| `search_terms` | list | `["Werkstudent", "working student"]` | Job search terms (env: `SEARCH_TERMS`) |
| `locations` | list | `["Germany"]` | Search locations (env: `LOCATIONS`) |
| `hours_old` | int | `24` | Only fetch jobs posted within this window |
| `results_wanted` | int | `500` | Max results per search-term/location pair |
| `fetch_description` | bool | `true` | Whether to fetch full job descriptions |
| `delay_ms_min` | int | `500` | Minimum delay between requests (ms) |
| `delay_ms_max` | int | `2000` | Maximum delay between requests (ms) |
| `http_proxy` | string | — | Optional HTTP proxy |
| `linkedin.li_at` | string | — | Optional LinkedIn auth cookie |
| `linkedin.jsessionid` | string | — | Optional LinkedIn session cookie |
| `linkedin.bsc` | string | — | Optional LinkedIn BSC cookie |

### `config.yaml` — Matcher Section

| Key | Type | Default | Description |
|---|---|---|---|
| `ai.stage1_model` | string | `llama-3.1-8b-instant` | Model for IT-role classification |
| `ai.stage2_model` | string | `llama-3.3-70b-versatile` | Model for profile scoring |
| `ai.rpm` | int | `30` | Requests per minute limit |
| `ai.tpm` | int | `80000` | Tokens per minute limit |
| `ai.safety_factor` | float | `0.9` | Fraction of TPM to actually use |
| `thresholds.include` | int | `75` | Minimum score for "include" label |
| `thresholds.maybe` | int | `55` | Minimum score for "maybe" label |
| `thresholds.min_score_to_alert` | int | `80` | Minimum score to trigger Telegram alert |
| `profile.summary` | string | — | Your professional summary for AI matching |
| `language_filter.enabled` | bool | `true` | Enable language-based filtering |
| `language_filter.german_exclude_threshold` | float | `0.9` | Confidence threshold for German exclusion |

### Environment Variables

| Variable | Required By | Description |
|---|---|---|
| `GROQ_API_KEY` | matcher, aggregator | Groq API key for LLM inference |
| `TELEGRAM_BOT_TOKEN` | matcher | Telegram bot token for notifications |
| `TELEGRAM_CHAT_ID` | matcher | Telegram chat ID for notifications |
| `SQLITE_PATH` | jobspy_api | Path to LinkedIn jobs database |
| `DATABASE_ENGINE` | seek_api, seek_scraper | `sqlite` or `postgres` |
| `SQLITE_DB_PATH` | seek_api (sqlite mode) | Path to Seek SQLite database |
| `SEEK_DATABASE_TABLE` | seek_api, seek_scraper | Database table name |
| `AGG_DB_PATH` | aggregator | Path to aggregator SQLite database |
| `AGG_AI_API_KEY` | aggregator | AI API key (falls back to `GROQ_API_KEY`) |
| `CONFIG_PATH` | matcher | Override path to `config.yaml` |
| `LOG_LEVEL` | all | Logging level (default: `INFO`) |

## Database Schema

The core pipeline uses SQLite in WAL mode with the following tables (managed by `infra/migrations/`):

- **`raw_jobs`** — Stores JSON payloads from scrapers with generated virtual columns (`title`, `company`, `location`, `description`, `job_url`) extracted from JSON.
- **`job_decisions`** — Final classification result per job (label, score, reasons, notification status).
- **`job_language_analysis`** — Stage 0 results (detected language, confidence, exclusion flag).
- **`job_stage1_results`** — Stage 1 results (IT-role boolean, confidence, reason).
- **`job_stage2_results`** — Stage 2 state and results (status, attempts, payload, errors).
- **`scrape_runs`** / **`scrape_errors`** — Scraper telemetry and error logging.
- **`ai_audit`** — Full request/response audit trail for all LLM API calls.
- **`schema_migrations`** — Migration tracking.

## CI/CD

Deployment is automated via GitHub Actions on push to `main` (`.github/workflows/deploy.yml`):

1. Checks out the repository on a self-hosted runner.
2. Writes secrets (`GROQ_API_KEY`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, proxy settings) to `infra/.env`.
3. Builds the Docker image tagged with the commit SHA.
4. Runs `docker compose up -d` with the production compose file.
5. Verifies database persistence at `/var/lib/jobs-app/data`.

Dependabot is configured (`.github/dependabot.yml`) to check weekly for updates across:
- Python packages in `flask_app/`, `matcher/`, and `jobspy_scraper/`
- Docker base images
- GitHub Actions versions

## Design Decisions and Trade-offs

- **SQLite as primary datastore**: Chosen for zero-ops simplicity. WAL mode enables concurrent reads during writes. The trade-off is limited write concurrency — only one writer should be active at a time. The Seek subsystem optionally supports PostgreSQL for heavier workloads.

- **JSON payloads with virtual columns**: `raw_jobs` stores the full scraper payload as JSON and uses SQLite generated columns to extract fields. This preserves the complete payload for debugging while enabling SQL queries on key fields.

- **Two-model matcher strategy**: Stage 1 uses a fast, small model for bulk title classification (cheap, fast). Stage 2 uses a larger model for detailed scoring of the remaining candidates. This keeps costs manageable.

- **Client-side rate limiting**: Rather than relying solely on 429 responses, the matcher estimates token usage before each request and proactively throttles. This reduces wasted requests and avoids API bans.

- **Separate databases per source**: The LinkedIn pipeline (`jobs.db`) and Seek pipeline (`seek_jobs.db`/PostgreSQL) use independent databases. The aggregator service bridges them by pulling from both APIs and deduplicating.

## Known Limitations

- **Minimal automated coverage only**: The repository now has four focused aggregator tests, but the scraper, matcher loop, Flask dashboard, and API endpoints still need broader coverage.
- **Hardcoded Flask DB path**: `flask_app/app.py` connects to `/app/data/jobs.db` (a Docker path). Running locally requires the database to exist at that path or a code change.
- **Stage 2 is currently disabled in the matcher loop**: The `claim_stage2_batch` call is commented out in `matcher/main.py`. Stage 2 processing does not execute in the current main loop.
- **Missing `import os` in `matcher/ai_client.py`**: The module references `os.getenv` without importing `os` at the module level.
- **Port conflicts**: Services bind to ports 5000, 6059, 6060, and 6061. Check for conflicts with local services.

## Detailed Sub-module Documentation

Each subsystem has its own README with endpoint specifications, environment variable matrices, and usage examples:

- [`jobspy_api/README.md`](jobspy_api/README.md) — JobSpy API endpoints and query parameters
- [`seek_api/README.md`](seek_api/README.md) — Seek API endpoints, filtering, and response format
- [`seek_scraper/README.md`](seek_scraper/README.md) — Seek spider setup, scheduling, regions, and troubleshooting
- [`aggregator_service/README.md`](aggregator_service/README.md) — Aggregator endpoints, AI config, and environment variables

## Testing

The deliberately small test suite exercises the aggregator's URL canonicalisation, AI-score validation, SQLite deduplication, and failed-sync checkpoint handling. It uses a temporary SQLite database and replaces source connectors with fakes; an autouse fixture fails the test immediately if code attempts a live HTTP request.

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --disable-pip-version-check -r requirements-test.txt
python -m pytest -q
```

No API keys, Telegram credentials, scraper access, production database, or Docker services are required.
