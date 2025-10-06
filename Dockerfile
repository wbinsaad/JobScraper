FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

WORKDIR /app

# System deps if needed by pandas/jobspy
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install both apps' deps (one image)
COPY scraper/requirements.txt /app/scraper/requirements.txt
COPY matcher/requirements.txt /app/matcher/requirements.txt
RUN pip install --no-cache-dir -r /app/scraper/requirements.txt \
    && pip install --no-cache-dir -r /app/matcher/requirements.txt

# Copy code
COPY . /app

# Create data dir
RUN mkdir -p /app/data

# No default; compose sets commands per service
CMD ["python", "-V"]
