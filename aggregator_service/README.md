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
- `GET /api/v1/profiles`
- `GET /api/v1/profiles/{profile_id}`
- `GET /api/v1/profiles/{profile_id}/jobs`
- `POST /api/v1/profiles`
- `PUT /api/v1/profiles/{profile_id}`
- `DELETE /api/v1/profiles/{profile_id}`
- `GET /api/v1/debug/api-requests`
- `GET /api/v1/debug/api-requests/{request_id}`

## Environment

- `AGG_DB_PATH` default `/app/data/aggregator.db`
- `AGG_MIG_DIR` default `/app/aggregator_service/migrations`
- `JOBSPY_API_BASE_URL` default `http://jobspy_api:8000`
- `SEEK_API_BASE_URL` default `http://seek_api:8000`
- `AGG_REQUEST_TIMEOUT_SECONDS` default `20`
- `AGG_SCHEDULER_ENABLED` default `true`
- `AGG_SCHEDULER_INTERVAL_SECONDS` default `900`
- `AGG_AI_BASE_URL` default `https://api.groq.com/openai/v1`
- `AGG_AI_MODEL` default `llama-3.3-70b-versatile`
- `AGG_AI_API_KEY` optional (falls back to `GROQ_API_KEY`)
- `AGG_AI_TIMEOUT_SECONDS` default `45`
- `AGG_AI_RPM` default `30`
- `AGG_AI_RPD` default `1000`
- `AGG_AI_TPM` default `12000`
- `AGG_AI_TPD` default `100000`
- `AGG_AI_MAX_REQUEST_TOKENS` default `6000`
- `AGG_AI_MAX_RESPONSE_TOKENS` default `256`
- `AGG_AI_SAFETY_FACTOR` default `0.9`
- `AGG_AI_SYSTEM_PROMPT` default is a JSON-only relevance scoring prompt

## Local run

```bash
python -m aggregator_service.migrate
uvicorn aggregator_service.main:app --reload --port 8010
```
