-- 002_ai_audit.sql (idempotent)
CREATE TABLE IF NOT EXISTS ai_audit (
  id               INTEGER PRIMARY KEY AUTOINCREMENT,
  ts_created       DATETIME DEFAULT CURRENT_TIMESTAMP,
  req_id           TEXT NOT NULL UNIQUE,
  provider         TEXT NOT NULL,       -- 'openai' | 'groq' | ...
  model            TEXT,
  endpoint         TEXT,                -- e.g. '/chat/completions'
  request_payload  TEXT NOT NULL,       -- JSON (stringified)
  response_payload TEXT,                -- JSON or raw text (stringified)
  status_code      INTEGER,
  latency_ms       INTEGER,
  error            TEXT
);
CREATE INDEX IF NOT EXISTS idx_ai_audit_ts ON ai_audit(ts_created);
CREATE INDEX IF NOT EXISTS idx_ai_audit_req ON ai_audit(req_id);
