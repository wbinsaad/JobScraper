PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;
PRAGMA foreign_keys=ON;
PRAGMA busy_timeout=5000;

-- 006_status_flag.sql
-- Purpose: Introduce a clear status on job_decisions to mark lifecycle: pending|approved|excluded

BEGIN TRANSACTION;

-- Add status column if it doesn't exist (SQLite: runner is idempotent by filename)
ALTER TABLE job_decisions ADD COLUMN status TEXT NOT NULL DEFAULT 'pending';

-- Backfill: any label='exclude' becomes excluded
UPDATE job_decisions SET status='excluded' WHERE label='exclude';

-- Backfill: mark approved where all stages already succeeded
-- Requires 005 to have created the normalized tables
UPDATE job_decisions
SET status='approved'
WHERE id IN (
  SELECT jd.id
  FROM job_decisions jd
  JOIN job_stage2_results s2 ON s2.job_decision_id = jd.id AND s2.status='ok'
  LEFT JOIN job_language_analysis la ON la.job_decision_id = jd.id
  LEFT JOIN job_stage1_results s1 ON s1.job_decision_id = jd.id
  WHERE COALESCE(la.excluded, 0) = 0
    AND COALESCE(s1.is_it_role, 1) = 1
);

-- Convenience view exposing is_excluded as a computed flag
DROP VIEW IF EXISTS v_job_decisions_enriched;
CREATE VIEW v_job_decisions_enriched AS
SELECT
  jd.*,
  CASE WHEN jd.status='excluded' OR jd.label='exclude' THEN 1 ELSE 0 END AS is_excluded
FROM job_decisions jd;

COMMIT;
