PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;
PRAGMA foreign_keys=ON;
PRAGMA busy_timeout=5000;

-- Raw jobs
CREATE TABLE IF NOT EXISTS raw_jobs (
  id           INTEGER PRIMARY KEY,
  source       TEXT NOT NULL DEFAULT 'linkedin',
  payload      TEXT NOT NULL,
  ingested_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  status       TEXT NOT NULL DEFAULT 'new',
  job_url      TEXT GENERATED ALWAYS AS (json_extract(payload, '$.job_url')) VIRTUAL,
  title        TEXT GENERATED ALWAYS AS (json_extract(payload, '$.title')) VIRTUAL,
  company      TEXT GENERATED ALWAYS AS (json_extract(payload, '$.company')) VIRTUAL,
  location     TEXT GENERATED ALWAYS AS (json_extract(payload, '$.location')) VIRTUAL,
  job_type     TEXT GENERATED ALWAYS AS (json_extract(payload, '$.job_type')) VIRTUAL,
  description  TEXT GENERATED ALWAYS AS (json_extract(payload, '$.description')) VIRTUAL
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_raw_jobs_job_url ON raw_jobs(job_url);
CREATE INDEX IF NOT EXISTS ix_raw_jobs_status ON raw_jobs(status);

-- Scrape telemetry (you already had these)
CREATE TABLE IF NOT EXISTS scrape_runs (
  id           INTEGER PRIMARY KEY,
  started_at   DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  finished_at  DATETIME,
  new_rows     INTEGER DEFAULT 0,
  error_count  INTEGER DEFAULT 0,
  params_json  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS scrape_errors (
  id           INTEGER PRIMARY KEY,
  run_id       INTEGER NOT NULL REFERENCES scrape_runs(id) ON DELETE CASCADE,
  ts           DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  scope        TEXT,
  error_type   TEXT,
  message      TEXT,
  context_json TEXT
);

-- Decisions + pipeline state (stage1/2)
CREATE TABLE IF NOT EXISTS job_decisions (
  id                INTEGER PRIMARY KEY,
  raw_job_id        INTEGER NOT NULL UNIQUE REFERENCES raw_jobs(id) ON DELETE CASCADE,

  -- Final decision
  label             TEXT,               -- include|maybe|exclude
  score             INTEGER,            -- 0..100
  reasons           TEXT,               -- JSON array of strings (from stage2)
  decided_at        DATETIME,
  notified_at       DATETIME,

  -- Stage-1 persisted
  stage1_json       TEXT,               -- {"interest","confidence","reason"}
  stage1_at         DATETIME,

  -- Stage-2 persisted + retryable
  stage2_json       TEXT,
  stage2_status     TEXT NOT NULL DEFAULT 'pending',  -- pending|processing|ok|error
  stage2_attempts   INTEGER NOT NULL DEFAULT 0,
  stage2_last_error TEXT
);
CREATE INDEX IF NOT EXISTS ix_job_decisions_label_score ON job_decisions(label, score);
CREATE INDEX IF NOT EXISTS ix_job_decisions_stage2 ON job_decisions(stage2_status, stage2_attempts);

-- Migration bookkeeping
CREATE TABLE IF NOT EXISTS schema_migrations (
  filename   TEXT PRIMARY KEY,
  applied_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);
