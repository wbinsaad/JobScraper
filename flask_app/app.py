from flask import Flask, render_template, request, redirect, url_for
from utils import time_ago
import sqlite3
from datetime import datetime
import json

app = Flask(__name__)

# Function to fetch data from SQLite database
def fetch_jobs(
    status: str = "all",
    time_min: int | None = None,
    time_max: int | None = None,
    q: str | None = None,
    limit: int = 500
):
    conn = sqlite3.connect('/app/data/jobs.db')  # Adjust the path if needed
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    conditions = []
    params = []

    # --- Status filter ---
    status = (status or "all").lower()
    if status in ("pending", "approved", "excluded"):
        conditions.append("LOWER(COALESCE(jd.status, 'pending')) = ?")
        params.append(status)
    elif status == "active":
        # everything except excluded
        conditions.append("LOWER(COALESCE(jd.status, 'pending')) <> ?")
        params.append("excluded")

    # --- Time range filter (slider support) ---
    # time_min and time_max are in hours from NOW backwards
    if time_min is not None and time_max is not None:
        # Convert hours to datetime range:
        # Include only jobs whose decided_at/ingested_at between now - max_hours and now - min_hours
        conditions.append("""
            COALESCE(jd.decided_at, job.ingested_at)
            BETWEEN datetime('now', ?) AND datetime('now', ?)
        """)
        params.append(f'-{int(time_max)} hours')
        params.append(f'-{int(time_min)} hours')

    # --- Text search ---
    if q:
        like = f"%{q}%"
        # Include language in server-side search
        conditions.append(
            "(job.title LIKE ? OR job.company LIKE ? OR job.job_url LIKE ? OR jla.language LIKE ?)"
        )
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
            s2.last_error     AS s2_last_error,

            -- Company logo from raw_jobs.payload JSON
            json_extract(job.payload, '$.company_logo') AS company_logo,
            job.payload AS payload_json
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

        # Fallback if JSON1 isn't available or company_logo is null
        if not job.get('company_logo'):
            try:
                payload_val = job.get('payload_json')
                if payload_val:
                    payload_obj = json.loads(payload_val) if isinstance(payload_val, (str, bytes)) else payload_val
                    if isinstance(payload_obj, dict):
                        job['company_logo'] = payload_obj.get('company_logo')
            except Exception:
                pass

        # Human-friendly scraped_ago
        if job.get('scraped_at'):
            try:
                scraped_dt = datetime.fromisoformat(job['scraped_at'])
                job['scraped_ago'] = time_ago(scraped_dt)
            except Exception:
                job['scraped_ago'] = "unknown"
        else:
            job['scraped_ago'] = "unknown"

        # Trim payload from the response to reduce size
        job.pop('payload_json', None)
        jobs.append(job)

    return jobs

# Route to display job data
@app.route('/')
def index():
    # Redirect to include status=active if missing/empty, preserving other query params
    if not request.args.get('status'):
        args = request.args.to_dict(flat=True)
        args['status'] = 'active'
        return redirect(url_for('index', **args), code=302)

    status = (request.args.get('status') or 'all').lower()
    q = (request.args.get('q') or '').strip()

    try:
        time_min = int(request.args.get('time_min')) if request.args.get('time_min') else None
        time_max = int(request.args.get('time_max')) if request.args.get('time_max') else None
    except ValueError:
        time_min = time_max = None

    jobs = fetch_jobs(status=status, time_min=time_min, time_max=time_max, q=q, limit=1000)
    return render_template(
        'index.html',
        jobs=jobs,
        status=status,
        time_min=time_min,
        time_max=time_max,
        q=q
    )

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
