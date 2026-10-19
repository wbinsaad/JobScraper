FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

WORKDIR /app

# Install system dependencies (if needed by pandas/jobspy or other dependencies)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install both apps' dependencies (jobspy_scraper and matcher)
COPY jobspy_scraper/requirements.txt /app/jobspy_scraper/requirements.txt
COPY matcher/requirements.txt /app/matcher/requirements.txt
RUN pip install --no-cache-dir -r /app/jobspy_scraper/requirements.txt \
    && pip install --no-cache-dir -r /app/matcher/requirements.txt

# Install Flask and any other dependencies for the Flask app
COPY flask_app/requirements.txt /app/flask_app/requirements.txt
RUN pip install --no-cache-dir -r /app/flask_app/requirements.txt

# Install dependencies for jobspy_api
COPY jobspy_api/requirements.txt /app/jobspy_api/requirements.txt
RUN pip install --no-cache-dir -r /app/jobspy_api/requirements.txt

# Copy Flask app code into the container
COPY flask_app /app/flask_app

# Copy the rest of the code (scraper, matcher, config files) into the container
COPY . /app

# Create data directory for the database
RUN mkdir -p /app/data

# Expose port 5000 for Flask app
EXPOSE 5000

# No default; compose sets commands per service
CMD ["python", "/app/flask_app/app.py"]
