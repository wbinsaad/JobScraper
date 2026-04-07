CREATE TABLE IF NOT EXISTS source_sync_runs (
    run_id INTEGER PRIMARY KEY,
    started_at TEXT NOT NULL,
    ended_at TEXT,
    overall_status TEXT NOT NULL,
    trigger_type TEXT,
    error_summary TEXT
);

CREATE TABLE IF NOT EXISTS source_run_details (
    id INTEGER PRIMARY KEY,
    run_id INTEGER NOT NULL,
    source_name TEXT NOT NULL,
    source_status TEXT NOT NULL,
    fetched_count INTEGER NOT NULL DEFAULT 0,
    inserted_count INTEGER NOT NULL DEFAULT 0,
    updated_count INTEGER NOT NULL DEFAULT 0,
    checkpoint_before TEXT,
    checkpoint_after TEXT,
    source_max_seen_ts TEXT,
    error_text TEXT,
    FOREIGN KEY(run_id) REFERENCES source_sync_runs(run_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS source_checkpoints (
    source_name TEXT PRIMARY KEY,
    last_success_ts TEXT,
    updated_at TEXT,
    last_run_id INTEGER
);

CREATE TABLE IF NOT EXISTS jobs_canonical (
    id INTEGER PRIMARY KEY,
    normalized_job_url TEXT NOT NULL UNIQUE,
    title TEXT,
    company TEXT,
    location TEXT,
    description TEXT,
    job_type TEXT,
    pay_range_text TEXT,
    first_seen_at TEXT,
    last_seen_at TEXT,
    active_flag INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS jobs_source_snapshot (
    id INTEGER PRIMARY KEY,
    canonical_job_id INTEGER NOT NULL,
    source_name TEXT NOT NULL,
    source_job_id TEXT,
    source_payload_json TEXT,
    source_posted_at TEXT,
    source_updated_at TEXT,
    observed_at TEXT NOT NULL,
    FOREIGN KEY(canonical_job_id) REFERENCES jobs_canonical(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS job_presence (
    canonical_job_id INTEGER NOT NULL,
    source_name TEXT NOT NULL,
    first_seen_at TEXT,
    last_seen_at TEXT,
    last_status TEXT,
    PRIMARY KEY(canonical_job_id, source_name),
    FOREIGN KEY(canonical_job_id) REFERENCES jobs_canonical(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS api_request_log (
    request_id INTEGER PRIMARY KEY,
    run_id INTEGER,
    task_id TEXT,
    source_name TEXT NOT NULL,
    method TEXT NOT NULL,
    url TEXT NOT NULL,
    query_json TEXT,
    headers_json_masked TEXT,
    request_body_json TEXT,
    requested_at TEXT NOT NULL,
    timeout_ms INTEGER,
    retry_no INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY(run_id) REFERENCES source_sync_runs(run_id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS api_response_log (
    response_id INTEGER PRIMARY KEY,
    request_id INTEGER NOT NULL,
    responded_at TEXT NOT NULL,
    duration_ms INTEGER,
    status_code INTEGER,
    response_headers_json TEXT,
    response_body_excerpt TEXT,
    body_sha256 TEXT,
    success_flag INTEGER NOT NULL,
    error_type TEXT,
    error_message TEXT,
    FOREIGN KEY(request_id) REFERENCES api_request_log(request_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS task_runs (
    id INTEGER PRIMARY KEY,
    task_id TEXT NOT NULL,
    started_at TEXT NOT NULL,
    ended_at TEXT,
    status TEXT NOT NULL,
    trigger_type TEXT,
    error_summary TEXT
);

CREATE INDEX IF NOT EXISTS idx_source_run_details_run ON source_run_details(run_id);
CREATE INDEX IF NOT EXISTS idx_source_checkpoints_updated ON source_checkpoints(updated_at);
CREATE INDEX IF NOT EXISTS idx_jobs_canonical_last_seen ON jobs_canonical(last_seen_at);
CREATE INDEX IF NOT EXISTS idx_jobs_snapshot_source_observed ON jobs_source_snapshot(source_name, observed_at);
CREATE INDEX IF NOT EXISTS idx_api_request_source_time ON api_request_log(source_name, requested_at DESC);
CREATE INDEX IF NOT EXISTS idx_api_request_run ON api_request_log(run_id);
CREATE INDEX IF NOT EXISTS idx_api_response_success_time ON api_response_log(success_flag, responded_at DESC);
CREATE INDEX IF NOT EXISTS idx_api_response_status_time ON api_response_log(status_code, responded_at DESC);
