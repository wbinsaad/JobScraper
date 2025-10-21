PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;
PRAGMA foreign_keys=ON;
PRAGMA busy_timeout=5000;

-- 005_split_stage_tables.sql
-- Purpose: Normalize stage-specific data out of job_decisions into dedicated tables
--          and keep job_decisions for final decisions only.
-- Notes:
--  - Designed for SQLite. Should also be compatible with PostgreSQL with minor syntax tweaks.
--  - Idempotency is managed by the migration runner applying each file once.
--  - Statements within attempt to be safe if re-run manually.

BEGIN TRANSACTION;

-- 1) Create normalized tables (if not exist)
CREATE TABLE IF NOT EXISTS job_stage1_results (
  id               INTEGER PRIMARY KEY,
  job_decision_id  INTEGER NOT NULL UNIQUE REFERENCES job_decisions(id) ON DELETE CASCADE,
  is_it_role       INTEGER,   -- 0 or 1
  confidence       REAL,
  reason           TEXT,
  created_at       DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS ix_job_stage1_results_jd ON job_stage1_results(job_decision_id);

CREATE TABLE IF NOT EXISTS job_stage2_results (
  id               INTEGER PRIMARY KEY,
  job_decision_id  INTEGER NOT NULL UNIQUE REFERENCES job_decisions(id) ON DELETE CASCADE,
  status           TEXT NOT NULL DEFAULT 'pending', -- pending|processing|ok|error
  attempts         INTEGER NOT NULL DEFAULT 0,
  last_error       TEXT,
  payload_json     TEXT,       -- JSON string of stage2 result
  updated_at       DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS ix_job_stage2_results_jd ON job_stage2_results(job_decision_id);

CREATE TABLE IF NOT EXISTS job_language_analysis (
  id               INTEGER PRIMARY KEY,
  job_decision_id  INTEGER NOT NULL UNIQUE REFERENCES job_decisions(id) ON DELETE CASCADE,
  lang_code        TEXT,
  confidence       REAL,
  excluded         INTEGER NOT NULL DEFAULT 0, -- 0 or 1
  created_at       DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS ix_job_language_analysis_jd ON job_language_analysis(job_decision_id);

-- 2) Backfill data from existing job_decisions columns (if present)
--    Pull from stage1_* and stage2_* and lang_* fields where available.
INSERT OR IGNORE INTO job_stage1_results (job_decision_id, is_it_role, confidence, reason, created_at)
SELECT jd.id,
       jd.stage1_is_it_role,
       jd.stage1_confidence,
       COALESCE(jd.stage1_reason, json_extract(jd.stage1_json, '$.reason')) AS reason,
       COALESCE(jd.stage1_at, CURRENT_TIMESTAMP)
FROM job_decisions jd
WHERE jd.stage1_is_it_role IS NOT NULL
   OR jd.stage1_confidence IS NOT NULL
   OR jd.stage1_json IS NOT NULL
   OR jd.stage1_reason IS NOT NULL;

INSERT OR IGNORE INTO job_stage2_results (job_decision_id, status, attempts, last_error, payload_json, updated_at)
SELECT jd.id,
       COALESCE(jd.stage2_status, 'pending') AS status,
       COALESCE(jd.stage2_attempts, 0) AS attempts,
       jd.stage2_last_error,
       jd.stage2_json,
       CURRENT_TIMESTAMP
FROM job_decisions jd
WHERE jd.stage2_status IS NOT NULL
   OR jd.stage2_attempts IS NOT NULL
   OR jd.stage2_last_error IS NOT NULL
   OR jd.stage2_json IS NOT NULL;

-- Language columns introduced in 004 may exist; if not, these will be NULL and filtered out by WHERE
INSERT OR IGNORE INTO job_language_analysis (job_decision_id, lang_code, confidence, excluded, created_at)
SELECT jd.id,
       jd.lang_code,
       jd.lang_confidence,
       COALESCE(jd.lang_excluded, 0),
       CURRENT_TIMESTAMP
FROM job_decisions jd
WHERE jd.lang_code IS NOT NULL OR jd.lang_confidence IS NOT NULL OR jd.lang_excluded IS NOT NULL;

-- 3) Compatibility view for read-only backward compatibility
DROP VIEW IF EXISTS v_full_job_decision;
CREATE VIEW v_full_job_decision AS
SELECT
  jd.id,
  jd.raw_job_id,
  jd.label,
  jd.score,
  jd.reasons,
  jd.decided_at,
  jd.notified_at,
  -- Stage1
  s1.is_it_role       AS stage1_is_it_role,
  s1.confidence       AS stage1_confidence,
  s1.reason           AS stage1_reason,
  s1.created_at       AS stage1_at,
  -- Stage2
  s2.status           AS stage2_status,
  s2.attempts         AS stage2_attempts,
  s2.last_error       AS stage2_last_error,
  s2.payload_json     AS stage2_json,
  -- Language
  la.lang_code        AS lang_code,
  la.confidence       AS lang_confidence,
  la.excluded         AS lang_excluded
FROM job_decisions jd
LEFT JOIN job_stage1_results s1 ON s1.job_decision_id = jd.id
LEFT JOIN job_stage2_results s2 ON s2.job_decision_id = jd.id
LEFT JOIN job_language_analysis la ON la.job_decision_id = jd.id;

-- 4) Remove stage-specific columns from job_decisions (schema slimming)
-- SQLite 3.35+ supports DROP COLUMN. If running on older SQLite, consider a table-rebuild migration.
-- Do these in a best-effort manner; if columns were never added, the runner won't re-apply this file.
-- Drop indexes that reference columns to be removed
DROP INDEX IF EXISTS ix_job_decisions_stage2;
-- Stage1 cols
ALTER TABLE job_decisions DROP COLUMN stage1_json;
ALTER TABLE job_decisions DROP COLUMN stage1_is_it_role;
ALTER TABLE job_decisions DROP COLUMN stage1_confidence;
ALTER TABLE job_decisions DROP COLUMN stage1_reason;
ALTER TABLE job_decisions DROP COLUMN stage1_at;
-- Stage2 cols
ALTER TABLE job_decisions DROP COLUMN stage2_json;
ALTER TABLE job_decisions DROP COLUMN stage2_status;
ALTER TABLE job_decisions DROP COLUMN stage2_attempts;
ALTER TABLE job_decisions DROP COLUMN stage2_last_error;
-- Language cols
ALTER TABLE job_decisions DROP COLUMN lang_code;
ALTER TABLE job_decisions DROP COLUMN lang_confidence;
ALTER TABLE job_decisions DROP COLUMN lang_excluded;

COMMIT;
