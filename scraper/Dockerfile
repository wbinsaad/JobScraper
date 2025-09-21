FROM python:3.12-slim

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates curl && rm -rf /var/lib/apt/lists/*

# Install deps first for better layer caching
COPY scraper/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy app code & schema
COPY scraper/ ./scraper
COPY scraper/schema.sql ./scraper/schema.sql

# default command: scheduler (runs once immediately, then hourly)
CMD ["python", "-m", "scraper.main", "serve", "--config", "/app/config.yaml"]
