from flask import Flask, render_template
import sqlite3

app = Flask(__name__)

# Function to fetch data from SQLite database
def fetch_jobs():
    conn = sqlite3.connect('data/jobs.db')  # Adjust the path if needed
    cursor = conn.cursor()
    
    query = """
        SELECT 
            job.id AS job_id,
            job.title AS job_title,
            job.company AS company_name,
            jd.score_model AS score,
            jd.is_it_role AS is_it_role,
            jd.confidence AS confidence,
            jd.stage1_json AS stage1_json
        FROM job AS job
        LEFT JOIN job_decisions AS jd
            ON job.id = jd.raw_job_id  -- adjust the join column if different
        ORDER BY jd.score_model DESC
        LIMIT 100
    """

    cursor.execute(query)  # Adjust SQL query to match your table
    jobs = cursor.fetchall()
    conn.close()
    return jobs

# Route to display job data
@app.route('/')
def index():
    jobs = fetch_jobs()  # Fetch job data from the database
    return render_template('index.html', jobs=jobs)

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
