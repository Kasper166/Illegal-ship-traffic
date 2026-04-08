# DARKWATER - Illegal Ship Traffic Monitoring

DARKWATER is a modular, containerized platform for detecting and analyzing potentially illegal maritime activity from SAR imagery.  
It combines machine-learning detection, AIS correlation, active learning, and a web dashboard in one Python monorepo.

## Live Demo

> **Try it now →** [darkwater.vercel.app](https://darkwater.vercel.app) *(read-only demo with sample data)*

The live demo showcases:
- Real-time vessel detection map (Gulf of Guinea)
- Filtering by confidence score, dark vessel status, and date range
- Data export (CSV / GeoJSON)
- Live detection feed via WebSocket
- Model performance statistics (mAP progression)

> Ingestion and model training are disabled in demo mode to prevent abuse.
> See [DEPLOYMENT.md](DEPLOYMENT.md) to deploy your own instance.

## Website

- Use the project website/repository here: [https://github.com/Kasper166/Illegal-ship-traffic](https://github.com/Kasper166/Illegal-ship-traffic)

## Key Features

- SAR data ingestion and preprocessing pipeline
- Vessel detection with YOLO-based inference/training workflows
- Dark-vessel assessment via AIS cross-referencing
- Similarity search with Qdrant for signature comparison
- Active learning loop with Label Studio integration
- FastAPI backend and dashboard frontend for monitoring and export

## Architecture

Core services in this repository:

- `ingestion`: Data acquisition and SAR preprocessing
- `detection`: Model training and batch inference
- `ais`: Global Fishing Watch integration and dark-vessel logic
- `active_learning`: Human-in-the-loop relabeling and retraining flow
- `dashboard/backend`: FastAPI APIs (`/api/detections`, stats, exports, live feed)
- `dashboard/frontend`: Web dashboard UI
- `shared`: Common schemas, logging, and shared state

Infrastructure services:

- `postgres` for metadata and detections
- `qdrant` for vector similarity search
- `label-studio` for annotation workflows

## Getting Started

### Run Locally

```bash
cp .env.example .env   # fill in your credentials
make up                # starts all services via Docker Compose
```

Open [http://localhost:5173](http://localhost:5173) for the dashboard.

### Quick Start (Detailed)

#### 1) Configure environment

```bash
cp .env.example .env
```

Fill in required secrets and credentials in `.env`.

#### 2) Build and run

```bash
make build
make up
```

#### 3) Access services

- Frontend: `http://localhost:8088`
- Backend API: `http://localhost:8000`
- Label Studio: `http://localhost:8080`
- Qdrant: `http://localhost:6333`

## Testing

Run fast tests (excluding slow integration tests):

```bash
pytest tests/ -m "not slow"
```

Run full end-to-end slow tests:

```bash
pytest tests/ -m "slow"
```

## CI/CD

GitHub Actions workflow includes:

- Ruff linting
- Mypy type checks
- Fast test suite on PRs and pushes
- Docker build verification for all service images
- Slow suite and GHCR image publishing on merge to `main`

## Repository Structure

```text
.
|-- active_learning/
|-- ais/
|-- dashboard/
|   |-- backend/
|   `-- frontend/
|-- detection/
|-- ingestion/
|-- shared/
|-- tests/
|-- docker-compose.yml
`-- .github/workflows/ci.yml
```
