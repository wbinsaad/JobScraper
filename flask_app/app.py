from flask import Flask, render_template, request
from utils import time_ago
import sqlite3
from datetime import datetime

app = Flask(__name__)

# Function to fetch data from SQLite database
def fetch_jobs(status: str = "all", time_window: str = "all", q: str | None = None, limit: int = 500):
    conn = sqlite3.connect('/app/data/jobs.db')  # Adjust the path if needed
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    conditions = []
    params = []

    status = (status or "all").lower()
    if status in ("pending", "approved", "excluded"):
        conditions.append("LOWER(COALESCE(jd.status, 'pending')) = ?")
        params.append(status)

    time_window = (time_window or "all").lower()
    if time_window in ("24h", "7d"):
        delta = "-24 hours" if time_window == "24h" else "-7 days"
        conditions.append("COALESCE(jd.decided_at, job.ingested_at) >= datetime('now', ?)")
        params.append(delta)

    if q:
        like = f"%{q}%"
        # Include language in server-side search
        conditions.append("(job.title LIKE ? OR job.company LIKE ? OR job.job_url LIKE ? OR jla.language LIKE ?)")
        params.extend([like, like, like, like])

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    query = f"""
        SELECT 
            job.id            AS job_id,
            job.title         AS job_title,
            job.company       AS company_name,
            job.job_url       AS job_url,
            job.ingested_at   AS scraped_at,

            jd.label          AS label,
            jd.score          AS score,
            jd.status         AS status,
            jd.decided_at     AS decision_at,

            -- Language analysis (Stage 0)
            jla.lang_code      AS language,
            ROUND(jla.confidence * 100) AS language_confidence,

            -- Stage 1 (role classification)
            s1.is_it_role     AS is_it_role,
            s1.confidence     AS confidence,

            -- Stage 2 (optional, if you need it in the UI)
            s2.status         AS s2_status,
            s2.attempts       AS s2_attempts,
            s2.last_error     AS s2_last_error
        FROM raw_jobs AS job
        LEFT JOIN job_decisions AS jd
            ON job.id = jd.raw_job_id
        -- If your schema links language analysis via job_decision_id (recommended):
        LEFT JOIN job_language_analysis AS jla
            ON jla.job_decision_id = jd.id
        -- If instead it links via raw_job_id, use:
        -- LEFT JOIN job_language_analysis AS jla ON jla.raw_job_id = job.id

        LEFT JOIN job_stage1_results AS s1
            ON s1.job_decision_id = jd.id
        LEFT JOIN job_stage2_results AS s2
            ON s2.job_decision_id = jd.id

        {where}
        ORDER BY COALESCE(s1.is_it_role, 0) DESC, COALESCE(s1.confidence, 0) DESC, job.ingested_at DESC
        LIMIT ?
    """
    params.append(int(limit))

    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()

    jobs = []
    for row in rows:
        job = dict(row)
        if job.get('scraped_at'):
            try:
                scraped_dt = datetime.fromisoformat(job['scraped_at'])
                job['scraped_ago'] = time_ago(scraped_dt)
            except Exception:
                job['scraped_ago'] = "unknown"
        else:
            job['scraped_ago'] = "unknown"
        jobs.append(job)

    return jobs

# Route to display job data
@app.route('/')
def index():
    status = (request.args.get('status') or 'all').lower()
    time_filter = (request.args.get('time') or 'all').lower()
    q = (request.args.get('q') or '').strip()
    # Increase the limit to cover typical use; keep reasonable cap
    jobs = fetch_jobs(status=status, time_window=time_filter, q=q, limit=1000)
    return render_template('index.html', jobs=jobs, status=status, time_filter=time_filter, q=q)

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
