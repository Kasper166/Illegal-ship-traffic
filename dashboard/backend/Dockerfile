FROM python:3.11-slim

WORKDIR /app

COPY dashboard/backend/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

COPY shared /app/shared
COPY dashboard/backend /app/dashboard/backend

ENV PYTHONPATH=/app

CMD ["uvicorn", "dashboard.backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
