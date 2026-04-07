FROM python:3.11-slim

WORKDIR /app

COPY active_learning/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

COPY shared /app/shared
COPY active_learning /app/active_learning

ENV PYTHONPATH=/app

CMD ["python", "-m", "active_learning.worker"]
