# Project Guidelines

## Code Style
- Follow existing Python style in each module and keep changes minimal and local.
- Preserve current import style and entrypoint patterns used in each service.
- Prefer focused fixes over broad refactors unless explicitly requested.
- Keep JSON payload handling robust (sanitize NaN/datetime-like values before serializing).

## Architecture
- Main flow for the core pipeline: scraper writes to SQLite raw tables, matcher performs staged AI decisions, Flask and FastAPI services read from DB.
- Key components:
  - scraper: LinkedIn scraping and ingestion into SQLite.
  - matcher: stage0 language filtering, stage1 IT-role classification, stage2 scoring/labeling.
  - flask_app: dashboard UI over SQLite data.
  - jobspy_api: read-only API for scraped jobs.
  - seek_scraper + seek_api: separate Seek scraping/API subsystem (sqlite or postgres configurable).
- Database schema changes are managed through SQL migrations in infra/migrations and applied by infra/migrate.py.

## Build and Test
- No automated tests or lint configuration are currently defined at repo level. Validate changes by running impacted service(s) directly.
- Common commands (run from repository root):
  - python infra/migrate.py
  - python -m jobspy_scraper.main run --config config.yaml
  - python -m jobspy_scraper.main serve --config config.yaml
  - python matcher/main.py
  - python flask_app/app.py
  - uvicorn jobspy_api.main:app --reload --port 8000
  - docker-compose -f infra/docker-compose.yml up
  - docker-compose -f docker-compose.flask.yml up

## Conventions
- Config is YAML-first via config.yaml for scraper/matcher, with selected environment-variable overrides in code.
- Treat migrations as prerequisite for any service expecting DB tables.
- SQLite is the default core datastore; preserve existing connection pragmas and transaction patterns when touching DB code.
- Keep component boundaries clear:
  - scraper should not embed matcher decision logic.
  - matcher should not implement UI/API concerns.
  - APIs/UI should remain read-oriented and avoid schema side effects.

## Known Pitfalls
- matcher/ai_client.py currently contains a hardcoded API key path/value pattern; prefer environment-based configuration for any new work.
- flask_app/app.py currently uses a fixed SQLite path (/app/data/jobs.db); keep this in mind when running outside containers.
- Service ports in compose can conflict locally (notably 5000, 6059, 6060).
- seek services require environment variables like SEEK_DATABASE_ENGINE and SEEK_DATABASE_TABLE in compose flows.

## Documentation Map
- Root overview is minimal: see README.md.
- JobSpy API usage and query examples: jobspy_api/README.md.
- Seek scraper setup, scheduling, env matrix, and troubleshooting: seek_scraper/README.md.
- Seek API endpoint behavior: seek_api/README.md.

## Agent Guidance
- Prefer linking to existing READMEs for detailed setup and endpoint semantics instead of duplicating docs.
- For multi-service changes, describe expected impact per component and list manual verification steps since tests are absent.
- When touching SQL schema or stage tables, preserve backward compatibility assumptions used by Flask/UI and APIs.
