FROM python:3.11-slim

WORKDIR /app

COPY ais/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

COPY shared /app/shared
COPY ais /app/ais

ENV PYTHONPATH=/app

CMD ["python", "-m", "ais.main"]
