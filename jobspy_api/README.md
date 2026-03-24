# JobSpy API (minimal read-only FastAPI)

This service exposes jobs stored by the existing scraper from the SQLite database (`raw_jobs` table).

## Assumptions
- Folder name is `jobspy_api` (request mentions `jobpy_api`; using existing folder in repo).
- Scraper DB is SQLite and contains `raw_jobs` from `infra/migrations/0001_base.sql`.
- `raw_jobs.ingested_at` is `DATETIME`, so range filtering is supported with `ingested_from`/`ingested_to`.

## Run locally
From project root:

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r jobspy_api/requirements.txt
uvicorn jobspy_api.main:app --reload --port 8000
```

If your DB is not at `data/jobs.db`, set env var:

```bash
set SQLITE_PATH=C:\path\to\jobs.db
```

## Endpoints
- `GET /health`
- `GET /api/v1/jobs`

### Query params for `/api/v1/jobs`
- `ingested_from` (optional, ISO datetime)
- `ingested_to` (optional, ISO datetime)
- `keyword` (optional, matches `title`/`company`/`description`)
- `location` (optional, matches `location`)
- `limit` (optional, default `50`, max `200`)
- `offset` (optional, default `0`)
- `sort_by` (optional: `ingested_at|title|company`, default `ingested_at`)
- `sort_order` (optional: `asc|desc`, default `desc`)

## Example requests
```bash
curl "http://127.0.0.1:8000/health"
curl "http://127.0.0.1:8000/api/v1/jobs"
curl "http://127.0.0.1:8000/api/v1/jobs?ingested_from=2026-03-20T00:00:00&ingested_to=2026-03-25T23:59:59"
curl "http://127.0.0.1:8000/api/v1/jobs?keyword=python&location=Berlin&limit=20&offset=0"
```

## Example response (`GET /api/v1/jobs`)
```json
{
  "total": 2,
  "limit": 50,
  "offset": 0,
  "items": [
    {
      "id": 101,
      "source": "linkedin",
      "title": "Working Student Backend Python",
      "company": "Example GmbH",
      "location": "Berlin, Germany",
      "job_type": "Part-time",
      "job_url": "https://...",
      "status": "new",
      "ingested_at": "2026-03-25 09:41:22"
    }
  ]
}
```
