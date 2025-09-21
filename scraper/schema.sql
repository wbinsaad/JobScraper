PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;
PRAGMA foreign_keys=ON;
PRAGMA busy_timeout=5000;

CREATE TABLE IF NOT EXISTS raw_jobs (
  id           INTEGER PRIMARY KEY,
  source       TEXT NOT NULL DEFAULT 'linkedin',
  payload      TEXT  NOT NULL,
  ingested_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  status       TEXT NOT NULL DEFAULT 'new',         -- new|processed|error

  job_url      TEXT GENERATED ALWAYS AS (json_extract(payload, '$.job_url')) VIRTUAL,
  title        TEXT GENERATED ALWAYS AS (json_extract(payload, '$.title')) VIRTUAL,
  company      TEXT GENERATED ALWAYS AS (json_extract(payload, '$.company')) VIRTUAL,
  location     TEXT GENERATED ALWAYS AS (json_extract(payload, '$.location')) VIRTUAL,
  job_type     TEXT GENERATED ALWAYS AS (json_extract(payload, '$.job_type')) VIRTUAL,
  description  TEXT GENERATED ALWAYS AS (json_extract(payload, '$.description')) VIRTUAL
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_raw_jobs_job_url ON raw_jobs(job_url);
CREATE INDEX IF NOT EXISTS ix_raw_jobs_status     ON raw_jobs(status);

CREATE TABLE IF NOT EXISTS scrape_runs (
  id             INTEGER PRIMARY KEY,
  started_at     DATETIME NOT NULL,
  finished_at    DATETIME,
  status         TEXT NOT NULL, -- running|success|partial|failed
  total_requests INTEGER DEFAULT 0,
  total_rows     INTEGER DEFAULT 0,
  new_rows       INTEGER DEFAULT 0,
  error_count    INTEGER DEFAULT 0,
  params_json    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS scrape_errors (
  id           INTEGER PRIMARY KEY,
  run_id       INTEGER NOT NULL REFERENCES scrape_runs(id) ON DELETE CASCADE,
  ts           DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  scope        TEXT,        -- e.g. "Werkstudent @ Berlin, Germany"
  error_type   TEXT,        -- timeout|http_429|http_5xx|parse|db
  message      TEXT,
  context_json TEXT
);
