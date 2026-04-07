from __future__ import annotations

import asyncio
import csv
import io
import json
import os
from contextlib import suppress
from datetime import UTC, datetime, time
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse
from sqlalchemy import and_, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from shared.schemas import (
    DetectionListResponse,
    DetectionRecord,
    DetectionRecordORM,
    ExportRequest,
    HealthResponse,
    IterationRecord,
    ModelMetricsORM,
    StatsResponse,
)

app = FastAPI(title="DARKWATER API", version="0.1.0")

DATABASE_URL = os.getenv("DATABASE_URL", "")
if not DATABASE_URL:
    raise ValueError("DATABASE_URL is required")

engine = create_async_engine(DATABASE_URL, future=True)
SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
ITERATIONS_PATH = Path(
    os.getenv(
        "ITERATIONS_JSON_PATH",
        str(Path(__file__).resolve().parents[2] / "active_learning" / "iterations.json"),
    )
)


class LivePubSub:
    def __init__(self) -> None:
        self._subscribers: set[asyncio.Queue[dict[str, Any]]] = set()
        self._lock = asyncio.Lock()

    async def subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=1000)
        async with self._lock:
            self._subscribers.add(queue)
        return queue

    async def unsubscribe(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        async with self._lock:
            self._subscribers.discard(queue)

    async def publish(self, payload: dict[str, Any]) -> None:
        async with self._lock:
            subscribers = list(self._subscribers)
        for queue in subscribers:
            with suppress(asyncio.QueueFull):
                queue.put_nowait(payload)


pubsub = LivePubSub()
poller_task: asyncio.Task[None] | None = None


def _to_detection(row: DetectionRecordORM) -> DetectionRecord:
    return DetectionRecord(
        id=row.id,
        patch_id=row.patch_id,
        tile_id=row.tile_id,
        bbox_xyxy=list(row.bbox_xyxy),
        pixel_coords=list(row.pixel_coords),
        confidence=row.confidence,
        class_label=row.class_label,
        lat_lon_center=(row.lat, row.lon),
        timestamp=row.timestamp,
        scene_id=row.scene_id,
        flagged_for_review=row.flagged_for_review,
        is_dark=row.is_dark,
    )


def _read_iterations() -> list[IterationRecord]:
    if not ITERATIONS_PATH.exists():
        return []
    payload = json.loads(ITERATIONS_PATH.read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        rows = payload.get("iterations", [])
    elif isinstance(payload, list):
        rows = payload
    else:
        rows = []
    return [IterationRecord.model_validate(item) for item in rows]


def _today_bounds_utc() -> tuple[datetime, datetime]:
    today = datetime.now(UTC).date()
    start = datetime.combine(today, time.min).replace(tzinfo=UTC)
    end = datetime.combine(today, time.max).replace(tzinfo=UTC)
    return start, end


async def get_session() -> AsyncSession:
    async with SessionLocal() as session:
        yield session


async def detection_poller() -> None:
    last_seen_id = 0
    while True:
        try:
            async with SessionLocal() as session:
                result = await session.execute(
                    select(DetectionRecordORM)
                    .where(DetectionRecordORM.id > last_seen_id)
                    .order_by(DetectionRecordORM.id.asc())
                    .limit(200)
                )
                rows = list(result.scalars().all())
                for row in rows:
                    last_seen_id = max(last_seen_id, row.id)
                    await pubsub.publish(_to_detection(row).model_dump(mode="json"))
        except Exception:
            # keep loop alive for live feed consumers
            await asyncio.sleep(2.0)
        await asyncio.sleep(1.0)


@app.on_event("startup")
async def on_startup() -> None:
    global poller_task
    poller_task = asyncio.create_task(detection_poller())


@app.on_event("shutdown")
async def on_shutdown() -> None:
    if poller_task:
        poller_task.cancel()
        with suppress(asyncio.CancelledError):
            await poller_task
    await engine.dispose()


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok")


@app.get("/api/detections", response_model=DetectionListResponse)
async def list_detections(
    dark_only: bool = Query(default=False),
    min_confidence: float = Query(default=0.0, ge=0.0, le=1.0),
    since: datetime | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=500),
    session: AsyncSession = Depends(get_session),
) -> DetectionListResponse:
    filters = [DetectionRecordORM.confidence >= min_confidence]
    if dark_only:
        filters.append(DetectionRecordORM.is_dark.is_(True))
    if since is not None:
        filters.append(DetectionRecordORM.timestamp >= since)

    where_clause = and_(*filters) if filters else True
    total_query = select(func.count()).select_from(DetectionRecordORM).where(where_clause)
    total = int((await session.execute(total_query)).scalar_one())

    query = (
        select(DetectionRecordORM)
        .where(where_clause)
        .order_by(desc(DetectionRecordORM.timestamp), desc(DetectionRecordORM.id))
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    rows = list((await session.execute(query)).scalars().all())
    return DetectionListResponse(
        total=total,
        page=page,
        page_size=page_size,
        items=[_to_detection(row) for row in rows],
    )


@app.get("/api/iterations", response_model=list[IterationRecord])
async def get_iterations() -> list[IterationRecord]:
    return _read_iterations()


@app.get("/api/stats", response_model=StatsResponse)
async def get_stats(session: AsyncSession = Depends(get_session)) -> StatsResponse:
    day_start, day_end = _today_bounds_utc()

    total_today_q = select(func.count()).select_from(DetectionRecordORM).where(
        DetectionRecordORM.timestamp >= day_start,
        DetectionRecordORM.timestamp <= day_end,
    )
    dark_count_q = select(func.count()).select_from(DetectionRecordORM).where(
        DetectionRecordORM.is_dark.is_(True)
    )
    latest_map_q = (
        select(ModelMetricsORM.map50)
        .order_by(desc(ModelMetricsORM.evaluated_at), desc(ModelMetricsORM.id))
        .limit(1)
    )

    total_today = int((await session.execute(total_today_q)).scalar_one())
    dark_count = int((await session.execute(dark_count_q)).scalar_one())
    latest_map = (await session.execute(latest_map_q)).scalar_one_or_none()

    iterations = _read_iterations()
    active_iter = iterations[-1].iteration if iterations else 0
    map_from_iterations = iterations[-1].map50 if iterations else 0.0

    return StatsResponse(
        total_detections_today=total_today,
        dark_vessel_count=dark_count,
        active_learning_iteration=active_iter,
        current_model_map=float(latest_map if latest_map is not None else map_from_iterations),
    )


@app.post("/api/export")
async def export_dark_vessels(
    body: ExportRequest, session: AsyncSession = Depends(get_session)
) -> StreamingResponse:
    query = select(DetectionRecordORM).where(DetectionRecordORM.is_dark.is_(True))
    rows = list((await session.execute(query)).scalars().all())
    records = [_to_detection(row) for row in rows]

    if body.format == "csv":
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(
            [
                "id",
                "patch_id",
                "tile_id",
                "confidence",
                "class_label",
                "lat",
                "lon",
                "timestamp",
                "scene_id",
                "flagged_for_review",
                "is_dark",
            ]
        )
        for det in records:
            writer.writerow(
                [
                    det.id,
                    det.patch_id,
                    det.tile_id,
                    det.confidence,
                    det.class_label,
                    det.lat_lon_center[0],
                    det.lat_lon_center[1],
                    det.timestamp.isoformat(),
                    det.scene_id,
                    det.flagged_for_review,
                    det.is_dark,
                ]
            )
        payload = buffer.getvalue().encode("utf-8")
        return StreamingResponse(
            io.BytesIO(payload),
            media_type="text/csv",
            headers={"Content-Disposition": 'attachment; filename="dark_vessels.csv"'},
        )

    features = []
    for det in records:
        features.append(
            {
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [det.lat_lon_center[1], det.lat_lon_center[0]],
                },
                "properties": {
                    "id": det.id,
                    "patch_id": det.patch_id,
                    "tile_id": det.tile_id,
                    "confidence": det.confidence,
                    "class_label": det.class_label,
                    "timestamp": det.timestamp.isoformat(),
                    "scene_id": det.scene_id,
                    "flagged_for_review": det.flagged_for_review,
                    "is_dark": det.is_dark,
                },
            }
        )
    geojson_payload = {"type": "FeatureCollection", "features": features}
    encoded = json.dumps(geojson_payload).encode("utf-8")
    return StreamingResponse(
        io.BytesIO(encoded),
        media_type="application/geo+json",
        headers={"Content-Disposition": 'attachment; filename="dark_vessels.geojson"'},
    )


@app.websocket("/ws/live")
async def ws_live(ws: WebSocket) -> None:
    await ws.accept()
    queue = await pubsub.subscribe()
    try:
        while True:
            payload = await queue.get()
            await ws.send_json(payload)
    except WebSocketDisconnect:
        pass
    finally:
        await pubsub.unsubscribe(queue)
