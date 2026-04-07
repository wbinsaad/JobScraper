FROM python:3.11-slim

WORKDIR /app

COPY aggregator_service/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY aggregator_service /app/aggregator_service

ENV PYTHONUNBUFFERED=1
ENV PORT=8010

EXPOSE 8010

CMD ["python", "-m", "uvicorn", "aggregator_service.main:app", "--host", "0.0.0.0", "--port", "8010"]
