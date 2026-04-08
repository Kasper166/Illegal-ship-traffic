# Project DARKWATER - System Instructions

## 1. Project Context
**Identity:** Production-grade maritime surveillance MLOps pipeline.
**Mission:** Detect "Dark Vessels" (Non-AIS) in the Gulf of Guinea using Sentinel-1 SAR.
**Stack:** Python 3.11, YOLOv8, FastAPI, Leaflet.js, Qdrant, PostgreSQL, Docker.

## 2. Critical Development Rules (NON-NEGOTIABLE)
- **Memory Safety:** NEVER `.read()` full 1GB+ SAR files. Use `rasterio.windows` for 512x512 patching.
- **Idempotency:** All ingestion/processing must check the Postgres `ProcessingStatus` state machine before execution to prevent double-processing.
- **Single Source of Truth:** Use `shared/schemas.py` for all Pydantic models. Do not define local versions in service directories.
- **Async Standard:** Use `async/await` with `httpx` for all network calls (GFW API, internal services).
- **No Secrets:** Never hardcode keys. Use `shared/config.py` to load from `.env`.

## 3. Core Commands
| Action | Command |
| :--- | :--- |
| **Infra** | `make up` / `make down` |
| **Linting** | `make lint` (ruff + mypy) |
| **Testing** | `pytest tests/` |
| **Ingest** | `python -m ingestion.downloader --days 6` |
| **Train** | `python -m detection.train --config config/yolo_baseline.yaml` |

## 4. Coding Style & Patterns
- **Types:** Strict type-hinting on all function signatures.
- **Errors:** Raise descriptive custom exceptions from `shared/exceptions.py`. No generic `print()`.
- **Imports:** Absolute imports only (e.g., `from shared.schemas import Detection`).
- **SAR Logic:** - Normalize pixels to [0,1] using 2nd/98th percentile clipping.
  - Apply Lee speckle filter (hand-coded `scipy` implementation).
  - Coastline masking (>60% land) is mandatory before inference.

## 5. Active Learning Workflow
- **Flagging:** `confidence < 0.45` OR `is_anomalous == True` -> Route to Label Studio.
- **Promotion:** New models are promoted to production only if `mAP@0.5` increases by >1% over current baseline.

## 6. Prohibited Actions
- **DO NOT** use default `pickle` for model saving; use `.pt` (PyTorch) or `.onnx`.
- **DO NOT** modify migration files in `alembic/versions/` once merged.
- **DO NOT** add new dependencies to `requirements.txt` without checking for license compatibility (MIT/Apache preferred).