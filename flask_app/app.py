from flask import Flask, render_template
from utils import time_ago
import sqlite3
from datetime import datetime

app = Flask(__name__)

# Function to fetch data from SQLite database
def fetch_jobs():
    conn = sqlite3.connect('/app/data/jobs.db')  # Adjust the path if needed
    conn.row_factory = sqlite3.Row  # To access columns by name
    cursor = conn.cursor()
    
    query = """
        SELECT 
            job.id AS job_id,
            job.title AS job_title,
            job.company AS company_name,
            job.job_url AS job_url,
            job.ingested_at AS scraped_at,
            jd.stage1_is_it_role AS is_it_role,
            jd.stage1_confidence AS confidence,
            jd.stage1_json AS stage1_json
        FROM raw_jobs AS job
        LEFT JOIN job_decisions AS jd
            ON job.id = jd.raw_job_id
        ORDER BY jd.stage1_is_it_role DESC , jd.stage1_confidence DESC
        LIMIT 100
    """

    cursor.execute(query)  # Adjust SQL query to match your table
    rows = cursor.fetchall()
    conn.close()

    jobs = []
    for row in rows:
        job = dict(row)

        # Convert scraped_at to datetime and compute relative time
        if job.get('scraped_at'):
            scraped_dt = datetime.fromisoformat(job['scraped_at'])
            job['scraped_ago'] = time_ago(scraped_dt)
        else:
            job['scraped_ago'] = "unknown"

        jobs.append(job)

    return jobs

# Route to display job data
@app.route('/')
def index():
    jobs = fetch_jobs()  # Fetch job data from the database
    return render_template('index.html', jobs=jobs)

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
