-- Migration to split stage1_json into separate columns
ALTER TABLE job_decisions ADD COLUMN stage1_is_it_role INTEGER; -- 0 = not IT, 1 = IT
ALTER TABLE job_decisions ADD COLUMN stage1_confidence REAL;
ALTER TABLE job_decisions ADD COLUMN stage1_reason TEXT;

-- Optionally, you may want to backfill these columns from stage1_json if needed.
-- Example (SQLite):
-- UPDATE job_decisions SET
--   stage1_interest = json_extract(stage1_json, '$.interest'),
--   stage1_confidence = json_extract(stage1_json, '$.confidence'),
--   stage1_reason = json_extract(stage1_json, '$.reason')
-- WHERE stage1_json IS NOT NULL;
