# Seek Jobs API

A lightweight, read-only FastAPI service for querying job listings from the Seek spider database.

## Features

- **RESTful API** with read-only endpoints
- **Filtering**: by region, work type, search terms, active status, and date field/range
- **Pagination**: limit and offset parameters
- **Sorting**: by posted_date, created_at, or updated_at
- **Health checks**: `/health` endpoint
- **Auto-generated documentation**: Swagger UI at `/docs`

## Endpoints

### Health Check
```
GET /health
```
Returns service health status.

### List Jobs
```
GET /jobs
```
Query parameters:
- `region` (optional): Filter by region (e.g., Melbourne, Perth)
- `search` (optional): Search in job titles and business names
- `work_type` (optional): Filter by work type
- `date_field` (optional): Which date column to filter on (posted_date | created_at | updated_at)
- `date_from` (optional): Inclusive start datetime (ISO 8601)
- `date_to` (optional): Inclusive end datetime (ISO 8601)
- `limit` (int, default: 20, max: 100): Number of results
- `offset` (int, default: 0): Pagination offset
- `sort_by` (default: posted_date): Sort field (posted_date | created_at | updated_at)
- `sort_order` (default: desc): Sort order (asc | desc)
- `is_active` (optional, bool): Filter by active status

**Example:**
```bash
GET /jobs?region=Melbourne&limit=10&sort_by=posted_date&sort_order=desc
```

**Date filter example:**
```bash
GET /jobs?date_field=created_at&date_from=2026-03-19T00:00:00Z&date_to=2026-03-19T23:59:59Z&limit=20
```

### Get Available Regions
```
GET /regions
```
Returns list of unique regions in the database.

**Example Response:**
```json
{
  "regions": ["Melbourne", "Perth", "Sydney"]
}
```

### Get Job by ID
```
GET /jobs/{job_id}
```
Returns detailed information for a specific job.

**Example:**
```bash
GET /jobs/91024499
```

## Running Locally

### With Docker Compose

```bash
docker compose up -d api
```

The API will be available at `http://localhost:8000`

### Without Docker

1. Install dependencies:
```bash
pip install -r api/requirements.txt
```

2. Set environment variables:
```bash
export POSTGRES_HOST=localhost
export POSTGRES_PORT=5432
export POSTGRES_USER=seekuser
export POSTGRES_PASSWORD=seekpass
export POSTGRES_DB=seekdb
export POSTGRES_TABLE=seek_jobs
```

3. Run the server:
```bash
python -m uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload
```

## API Documentation

Once running, visit:
- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| POSTGRES_HOST | postgres | PostgreSQL host |
| POSTGRES_PORT | 5432 | PostgreSQL port |
| POSTGRES_USER | seekuser | Database user |
| POSTGRES_PASSWORD | seekpass | Database password |
| POSTGRES_DB | seekdb | Database name |
| POSTGRES_TABLE | seek_jobs | Table name |

## Example Usage

### Get all Melbourne jobs
```bash
curl "http://localhost:8000/jobs?region=Melbourne&limit=20"
```

### Search for Python jobs
```bash
curl "http://localhost:8000/jobs?search=Python&limit=20"
```

### Get active IT jobs sorted by newest first
```bash
curl "http://localhost:8000/jobs?work_type=IT&is_active=true&sort_by=posted_date&sort_order=desc&limit=50"
```

### Paginate results
```bash
# First page (default limit=20)
curl "http://localhost:8000/jobs?offset=0"

# Second page
curl "http://localhost:8000/jobs?offset=20"
```

### Get a specific job's details
```bash
curl "http://localhost:8000/jobs/91024499"
```

## Response Format

All responses return JSON. Successful list queries return:

```json
{
  "total": 150,
  "limit": 20,
  "offset": 0,
  "items": [
    {
      "id": "91024499",
      "job_title": "Senior Software Engineer",
      "business_name": "Tech Corp",
      "work_type": "Full Time",
      "pay_range": "$100k - $120k",
      "suburb": "Melbourne",
      "area": "Vic",
      "region": "Melbourne",
      "url": "https://...",
      "advertiser_id": "123",
      "job_type": "Permanent",
      "posted_date": "2025-03-19T10:30:00",
      "created_at": "2025-03-19T10:35:00",
      "updated_at": "2025-03-19T10:35:00",
      "is_active": true,
      "is_new": true
    }
  ]
}
```

## Error Responses

### Not Found (404)
```json
{
  "detail": "Job not found"
}
```

### Server Error (500)
```json
{
  "detail": "Failed to retrieve jobs"
}
```

### Database Unavailable (503)
```json
{
  "detail": "Database connection failed"
}
```

## Performance Tips

1. Always use `limit` parameter (default 20 helps with performance)
2. Add filters (`region`, `work_type`) to reduce result set
3. Use `sort_by` and `sort_order` for efficient sorting (indexed columns available for posted_date, created_at)
4. Database has indexes on Region, PostedDate, IsActive, UpdatedAt for fast queries
