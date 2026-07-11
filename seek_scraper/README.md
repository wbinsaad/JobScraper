# Seek Scraper

Scrapy-based spider that scrapes IT job listings from Seek.com.au across Australian regions, with an APScheduler-driven scheduler for automated weekday/weekend runs and an optional backfill step for job descriptions.

## How It Works

1. The **scheduler** (`main.py`) launches Scrapy crawls as subprocesses on configurable cron schedules.
2. The **spider** (`SeekSpider/spiders/seek.py`) iterates through all IT subcategories (classification `6281`) via Seek's search API, then visits each job detail page for metadata (suburb, work type, salary).
3. The **pipeline** upserts jobs into the database, marks jobs not found in the current scrape as inactive (per region), and exports results to JSONL files.
4. The **backfill** module (`SeekSpider/backfill/`) separately fetches full job descriptions using a headless Chromium browser to handle Cloudflare challenges.

> **Note**: The spider intentionally does not scrape `JobDescription` — this is handled exclusively by the backfill script to avoid overwriting existing descriptions.

## Supported Regions

Perth, Sydney, Melbourne, Brisbane, Gold Coast, Adelaide, Canberra, Hobart, Darwin.

Configured in `SeekSpider/core/regions.py`. Default: `Perth`.

## Project Structure

```
seek_scraper/
├── main.py                  # APScheduler entry point
├── scrapy.cfg               # Scrapy project config
├── Dockerfile               # Python 3.11 + Chromium (for backfill)
├── requirements.txt
├── .env.example             # Environment template
├── SeekSpider/
│   ├── spiders/seek.py      # Main spider (Seek API + detail pages)
│   ├── pipelines.py         # DB upsert + JSON export + expiry marking
│   ├── middlewares.py       # Custom retry + fake user-agent
│   ├── settings.py          # Scrapy settings
│   ├── items.py             # Item schema
│   ├── core/
│   │   ├── config.py        # Env-based config with validation
│   │   ├── database.py      # DatabaseManager (SQLite / PostgreSQL)
│   │   ├── regions.py       # Region → Seek location mapping
│   │   ├── output_manager.py
│   │   └── logger.py
│   └── backfill/            # Headless browser job description fetcher
│       ├── __main__.py      # CLI entry point
│       ├── core.py          # Backfill logic
│       ├── config.py        # Backfill config
│       └── drivers.py       # Chromium/Selenium driver setup
└── docker/
    ├── postgres/             # PostgreSQL init SQL
    └── sqlite/               # SQLite init SQL
```

## Environment Variables

Copy `.env.example` to `.env` for local development. In CI/CD, set variables directly in the runtime environment.

| Variable | Required | Default | Description |
|---|---|---|---|
| `DATABASE_ENGINE` | yes | — | `sqlite` or `postgres` |
| `SQLITE_DB_PATH` | if sqlite | — | Path to SQLite database file |
| `DATABASE_TABLE` | yes | — | Table name (e.g. `seek_jobs`) |
| `POSTGRESQL_HOST` | if postgres | — | PostgreSQL host |
| `POSTGRESQL_PORT` | if postgres | — | PostgreSQL port |
| `POSTGRESQL_USER` | if postgres | — | PostgreSQL user |
| `POSTGRESQL_PASSWORD` | if postgres | — | PostgreSQL password |
| `POSTGRESQL_DATABASE` | if postgres | — | PostgreSQL database name |

Aliases `POSTGRES_HOST`, `POSTGRES_PORT`, etc. are supported for backward compatibility. Canonical names take precedence.

### Scheduler Variables

| Variable | Default | Description |
|---|---|---|
| `SCHEDULER_TIMEZONE` | `Australia/Melbourne` | Timezone for schedule triggers |
| `WEEKDAY_SCHEDULE_TIMES` | `08:00,10:00,...,22:00` | Comma-separated `HH:MM` times (Mon–Fri) |
| `WEEKEND_SCHEDULE_TIMES` | `10:00,14:00,18:00,22:00` | Comma-separated `HH:MM` times (Sat–Sun) |
| `SPIDER_NAME` | `seek` | Scrapy spider name |
| `SPIDER_ARGS` | `region=Melbourne` | `key=value` pairs passed to spider |
| `RUN_ON_START` | `true` | Run one immediate crawl on startup |
| `BACKFILL_AFTER_SCRAPE` | `false` | Chain backfill after each successful scrape |
| `BACKFILL_ARGS` | — | CLI args for backfill (e.g. `--region-filter Melbourne --limit 100`) |

## Running Locally

### Direct

```bash
pip install -r requirements.txt

# Run spider once for a region
scrapy crawl seek -a region=Melbourne

# Run the scheduler (cron-based)
python main.py
```

### Docker Compose (from project root)

```bash
# Via the infra compose
docker compose -f infra/docker-compose.yml up seek_scraper
```

### Backfill Job Descriptions

```bash
python -m SeekSpider.backfill --region-filter Melbourne --limit 100
```

> **Warning**: Backfill uses headless Chromium which is resource-intensive. Keep `--limit` conservative when running alongside the scraper to avoid SQLite lock contention.

## Database

- **SQLite**: Schema auto-initialised on startup from `docker/sqlite/init/001-init-seek_jobs.sqlite.sql`.
- **PostgreSQL**: Init SQL in `docker/postgres/init/`.

Both engines are supported interchangeably via `DATABASE_ENGINE`. The `DatabaseManager` normalises query placeholders (`%s` ↔ `?`) transparently.

## Key Design Decisions

- **Spider does not write `JobDescription`**: Only the backfill script writes descriptions, preventing accidental overwrites from Cloudflare-blocked responses returning empty content.
- **Per-region expiry**: When a scrape completes, jobs for that region not found in the current run are marked `IsActive=false`. Other regions are unaffected.
- **Threading locks**: `RUN_LOCK` and `BACKFILL_LOCK` prevent overlapping scrape or backfill runs from concurrent scheduler triggers.
- **Dual-engine support**: SQLite for zero-ops local/dev; PostgreSQL for production workloads.
