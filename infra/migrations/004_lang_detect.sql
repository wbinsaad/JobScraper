-- Migration 004_lang_detect.sql
ALTER TABLE job_decisions ADD COLUMN lang_code TEXT DEFAULT NULL;
ALTER TABLE job_decisions ADD COLUMN lang_confidence REAL DEFAULT NULL;
ALTER TABLE job_decisions ADD COLUMN lang_excluded INTEGER DEFAULT 0; -- 1 if excluded by language filter
