FROM python:3.11-slim

WORKDIR /app

COPY ingestion/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

COPY shared /app/shared
COPY ingestion /app/ingestion

ENV PYTHONPATH=/app

CMD ["python", "-m", "ingestion.main"]
