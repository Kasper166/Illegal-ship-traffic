# DARKWATER

Production-grade Python monorepo scaffold for:
- SAR ingestion
- YOLOv8 vessel detection
- Active learning with Label Studio
- AIS cross-referencing with Qdrant
- FastAPI + Leaflet.js dashboard

## Quick start

1. Copy `.env.example` to `.env` and set real secrets.
2. Build images:
   - `make build`
3. Start platform services:
   - `make up`

Frontend is exposed on `http://localhost:8088`.
Backend API is exposed on `http://localhost:8000`.
