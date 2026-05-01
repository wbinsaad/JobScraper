FROM python:3.11-slim

WORKDIR /app

# Install system dependencies including Chrome and virtual display
RUN apt-get update && apt-get install -y \
    gcc \
    libxml2-dev \
    libxslt-dev \
    curl \
    wget \
    gnupg \
    xvfb \
    xauth \
    && rm -rf /var/lib/apt/lists/*

# Install Chromium (works on both amd64 and arm64)
RUN apt-get update && apt-get install -y \
    chromium \
    chromium-driver \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1 \
    TZ=Australia/Melbourne \
    SCRAPY_PROJECT_DIR=/app \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Keep tzdata for reliable timezone/zoneinfo behavior, but cache apt metadata/packages
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update \
    && apt-get install -y --no-install-recommends tzdata \
    && rm -rf /var/lib/apt/lists/*

# Copy only dependency manifest first to maximize cache reuse
COPY seek_scraper/requirements.txt .

# Reuse pip download/wheel cache across rebuilds
RUN --mount=type=cache,target=/root/.cache/pip \
    python -m pip install -r requirements.txt

# Install additional pipeline requirements
RUN pip install --no-cache-dir \
    python-dateutil \
    pandas \
    undetected-chromedriver \
    selenium \
    pyvirtualdisplay

# Safest behavior-preserving copy.
# If you confirm the exact runtime files, replace this with narrower COPY lines.
COPY seek_scraper/ /app/

CMD ["python", "main.py"]