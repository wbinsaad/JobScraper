# Aggregator Service

Standalone FastAPI service that:
- Pulls jobs from JobSpy API and Seek API.
- Deduplicates by normalized job URL into a canonical table.
- Stores source snapshots and source checkpoints.
- Logs every outbound API request/response for debugging.
- Exposes debug endpoints for API request history.

## Endpoints

- `GET /api/v1/health`
- `POST /api/v1/sync`
- `GET /api/v1/status`
- `GET /api/v1/jobs`
- `GET /api/v1/debug/api-requests`
- `GET /api/v1/debug/api-requests/{request_id}`

## Environment

- `AGG_DB_PATH` default `/app/data/aggregator.db`
- `AGG_MIG_DIR` default `/app/aggregator_service/migrations`
- `JOBSPY_API_BASE_URL` default `http://jobspy_api:8000`
- `SEEK_API_BASE_URL` default `http://seek_api:8000`
- `AGG_REQUEST_TIMEOUT_SECONDS` default `20`
- `AGG_SCHEDULER_ENABLED` default `true`
- `AGG_SCHEDULER_INTERVAL_SECONDS` default `600`

## Local run

```bash
python -m aggregator_service.migrate
uvicorn aggregator_service.main:app --reload --port 8010
```
