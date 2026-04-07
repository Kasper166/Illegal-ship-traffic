FROM python:3.11-slim

WORKDIR /app

COPY detection/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

COPY shared /app/shared
COPY detection /app/detection

ENV PYTHONPATH=/app

CMD ["python", "-m", "detection.train"]
