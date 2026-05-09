CREATE TABLE IF NOT EXISTS profiles (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    cv_markdown TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS job_run_changes (
    id INTEGER PRIMARY KEY,
    run_id INTEGER NOT NULL,
    canonical_job_id INTEGER NOT NULL,
    change_type TEXT NOT NULL,
    changed_at TEXT NOT NULL,
    UNIQUE(run_id, canonical_job_id),
    FOREIGN KEY(run_id) REFERENCES source_sync_runs(run_id) ON DELETE CASCADE,
    FOREIGN KEY(canonical_job_id) REFERENCES jobs_canonical(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS ai_audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts_created TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    req_id TEXT NOT NULL UNIQUE,
    provider TEXT NOT NULL,
    model TEXT,
    endpoint TEXT,
    request_payload TEXT NOT NULL,
    response_payload TEXT,
    status_code INTEGER,
    latency_ms INTEGER,
    error TEXT
);

CREATE TABLE IF NOT EXISTS profile_job_score_queue (
    id INTEGER PRIMARY KEY,
    run_id INTEGER NOT NULL,
    profile_id INTEGER NOT NULL,
    canonical_job_id INTEGER NOT NULL,
    queued_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    attempts INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    UNIQUE(run_id, profile_id, canonical_job_id),
    FOREIGN KEY(run_id) REFERENCES source_sync_runs(run_id) ON DELETE CASCADE,
    FOREIGN KEY(profile_id) REFERENCES profiles(id) ON DELETE CASCADE,
    FOREIGN KEY(canonical_job_id) REFERENCES jobs_canonical(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS profile_job_scores (
    id INTEGER PRIMARY KEY,
    profile_id INTEGER NOT NULL,
    canonical_job_id INTEGER NOT NULL,
    run_id INTEGER NOT NULL,
    score INTEGER NOT NULL CHECK(score >= 0 AND score <= 9),
    scored_at TEXT NOT NULL,
    request_id TEXT,
    FOREIGN KEY(profile_id) REFERENCES profiles(id) ON DELETE CASCADE,
    FOREIGN KEY(canonical_job_id) REFERENCES jobs_canonical(id) ON DELETE CASCADE,
    FOREIGN KEY(run_id) REFERENCES source_sync_runs(run_id) ON DELETE CASCADE,
    FOREIGN KEY(request_id) REFERENCES ai_audit(req_id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_job_run_changes_run ON job_run_changes(run_id);
CREATE INDEX IF NOT EXISTS idx_job_run_changes_job ON job_run_changes(canonical_job_id);
CREATE INDEX IF NOT EXISTS idx_ai_audit_ts ON ai_audit(ts_created);
CREATE INDEX IF NOT EXISTS idx_ai_audit_req ON ai_audit(req_id);
CREATE INDEX IF NOT EXISTS idx_score_queue_status ON profile_job_score_queue(status, queued_at);
CREATE INDEX IF NOT EXISTS idx_score_queue_profile ON profile_job_score_queue(profile_id, queued_at);
CREATE INDEX IF NOT EXISTS idx_profile_scores_profile_job ON profile_job_scores(profile_id, canonical_job_id);
CREATE INDEX IF NOT EXISTS idx_profile_scores_run ON profile_job_scores(run_id);
