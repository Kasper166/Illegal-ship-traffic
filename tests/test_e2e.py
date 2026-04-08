from __future__ import annotations

import asyncio
import importlib
import time
from datetime import datetime, timezone

UTC = timezone.utc
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx
from fastapi.testclient import TestClient
from qdrant_client import QdrantClient
from qdrant_client.http import models as qmodels
from sqlalchemy import create_engine, func, select
from testcontainers.core.container import DockerContainer
from testcontainers.postgres import PostgresContainer

from ais.dark_vessel_detector import assess_dark_vessel
from ais.gfw_client import GFWClient
from detection.inference import Detection, run_inference
from shared.schemas import Base, DetectionRecordORM


class FakeTensor1D:
    def __init__(self, values: list[float]) -> None:
        self._values = values

    def __getitem__(self, idx: int) -> "FakeScalar":
        return FakeScalar(self._values[idx])

    def tolist(self) -> list[float]:
        return list(self._values)


class FakeScalar:
    def __init__(self, value: float) -> None:
        self._value = value

    def item(self) -> float:
        return self._value


class FakeBox:
    def __init__(self, xyxy: list[float], conf: float, cls_idx: int) -> None:
        self.xyxy = [FakeTensor1D(xyxy)]
        self.conf = FakeTensor1D([conf])
        self.cls = FakeTensor1D([float(cls_idx)])


class FakeResult:
    def __init__(self, boxes: list[FakeBox], orig_shape: tuple[int, int]) -> None:
        self.boxes = boxes
        self.orig_shape = orig_shape


class FakeYOLO:
    def __init__(self, model_path: str) -> None:
        self.model_path = model_path
        self.names = {0: "fishing"}

    def predict(
        self,
        source: list[str],
        conf: float,
        device: str,
        verbose: bool,
    ) -> list[FakeResult]:
        _ = (conf, device, verbose)
        return [
            FakeResult(
                boxes=[FakeBox([20.0, 30.0, 80.0, 110.0], conf=0.72, cls_idx=0)],
                orig_shape=(512, 512),
            )
            for _ in source
        ]


class FakeWandbRun:
    def finish(self) -> None:
        return None


class FakeWandb:
    def init(self, **kwargs: Any) -> FakeWandbRun:
        _ = kwargs
        return FakeWandbRun()

    def log(self, payload: dict[str, Any]) -> None:
        _ = payload
        return None

    def save(self, path: str) -> None:
        _ = path
        return None


class _FakeRedis:
    _store: dict[str, str] = {}

    async def get(self, key: str) -> str | None:
        return self._store.get(key)

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        _ = ex
        self._store[key] = value

    async def aclose(self) -> None:
        return None


def _to_asyncpg_url(sync_url: str) -> str:
    return (
        sync_url.replace("postgresql+psycopg2://", "postgresql+asyncpg://", 1)
        .replace("postgresql+psycopg://", "postgresql+asyncpg://", 1)
        .replace("postgresql://", "postgresql+asyncpg://", 1)
    )


def _to_psycopg_url(url: str) -> str:
    return (
        url.replace("postgresql+asyncpg://", "postgresql+psycopg://", 1)
        .replace("postgresql+psycopg2://", "postgresql+psycopg://", 1)
        .replace("postgresql://", "postgresql+psycopg://", 1)
    )


def _fixtures_scene_dir() -> Path:
    return Path(__file__).parent / "fixtures" / "scene_e2e"


def _wait_for_qdrant(qdrant_url: str, timeout_s: float = 30.0) -> QdrantClient:
    client = QdrantClient(url=qdrant_url)
    started = datetime.now(UTC)
    while (datetime.now(UTC) - started).total_seconds() < timeout_s:
        try:
            client.get_collections()
            return client
        except Exception:
            time.sleep(0.5)
    raise AssertionError("Qdrant did not become healthy in time for the e2e test.")


def _seed_postgres(sync_db_url: str, detections: list[Detection], is_dark_map: dict[str, bool]) -> None:
    engine = create_engine(sync_db_url, future=True)
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        for det in detections:
            lat, lon = det.lat_lon_center
            conn.execute(
                DetectionRecordORM.__table__.insert().values(
                    patch_id=det.patch_id,
                    tile_id=det.tile_id,
                    bbox_xyxy=det.bbox_xyxy,
                    pixel_coords=det.pixel_coords,
                    confidence=det.confidence,
                    class_label=det.class_label,
                    lat=lat,
                    lon=lon,
                    timestamp=det.timestamp,
                    scene_id=det.scene_id,
                    flagged_for_review=det.flagged_for_review,
                    is_dark=is_dark_map[det.patch_id],
                    metadata={},
                    created_at=datetime.now(UTC),
                )
            )
    engine.dispose()


def _count_postgres_rows(sync_db_url: str) -> int:
    engine = create_engine(sync_db_url, future=True)
    with engine.connect() as conn:
        row_count = int(
            conn.execute(select(func.count()).select_from(DetectionRecordORM.__table__)).scalar_one()
        )
    engine.dispose()
    return row_count


async def _idle_poller() -> None:
    await asyncio.sleep(3600)


@pytest.mark.slow
def test_pipeline_e2e_with_real_postgres_qdrant_and_api(monkeypatch, tmp_path: Path) -> None:
    fixture_scene = _fixtures_scene_dir()
    assert fixture_scene.exists(), "Fixture directory must exist at tests/fixtures/scene_e2e."

    with PostgresContainer("postgres:16-alpine") as postgres, DockerContainer("qdrant/qdrant:v1.15.4").with_exposed_ports(6333) as qdrant:
        sync_db_url = _to_psycopg_url(postgres.get_connection_url())
        db_url = _to_asyncpg_url(sync_db_url)
        monkeypatch.setenv("DATABASE_URL", db_url)
        monkeypatch.setenv("ACTIVE_LEARNING_THRESHOLD", "0.45")

        inference_module = importlib.import_module("detection.inference")
        monkeypatch.setattr(inference_module, "YOLO", FakeYOLO)
        monkeypatch.setattr(inference_module, "wandb", FakeWandb())

        output_jsonl = tmp_path / "detections.jsonl"
        run_inference(
            patches_dir=fixture_scene.parent,
            model_path=tmp_path / "fake-model.pt",
            output_jsonl=output_jsonl,
            batch_size=2,
        )
        assert output_jsonl.exists(), "Inference must produce detections.jsonl output."

        lines = output_jsonl.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 3, "Three fixture patches must yield exactly three detections in JSONL."

        detections = [Detection.model_validate_json(line) for line in lines]
        for det in detections:
            assert det.patch_id.startswith("patch_"), "Each detection patch_id must follow the expected patch naming scheme."
            assert len(det.bbox_xyxy) == 4, "Each detection must include four bbox coordinates."
            assert isinstance(det.flagged_for_review, bool), "Each detection must expose flagged_for_review as a boolean."

        # Mock redis cache to avoid external dependency while keeping real HTTP mocking with respx.
        gfw_module = importlib.import_module("ais.gfw_client")
        monkeypatch.setattr(gfw_module.Redis, "from_url", lambda *args, **kwargs: _FakeRedis())

        gfw = GFWClient(
            api_key="test-key",
            base_url="https://gfw.example.test",
            redis_url="redis://unused",
            timeout_s=5.0,
            max_retries=1,
        )

        with asyncio.Runner() as runner:
            with respx.mock(assert_all_called=True) as respx_mock:
                route = respx_mock.get("https://gfw.example.test/v3/ais/vessels/positions").mock(
                    side_effect=[
                        httpx.Response(200, json={"data": []}),
                        httpx.Response(
                            200,
                            json={
                                "data": [
                                    {
                                        "mmsi": "123456789",
                                        "vessel_name": "Known AIS Vessel",
                                        "lat": detections[1].lat_lon_center[0],
                                        "lon": detections[1].lat_lon_center[1],
                                        "timestamp": datetime.now(UTC).isoformat(),
                                    }
                                ]
                            },
                        ),
                    ]
                )

                pos_records = runner.run(
                    gfw.query_nearby_vessels(
                        lat=detections[0].lat_lon_center[0],
                        lon=detections[0].lat_lon_center[1],
                        timestamp=detections[0].timestamp,
                        radius_m=500,
                    )
                )
                neg_records = runner.run(
                    gfw.query_nearby_vessels(
                        lat=detections[1].lat_lon_center[0],
                        lon=detections[1].lat_lon_center[1] + 0.0001,
                        timestamp=detections[1].timestamp,
                        radius_m=500,
                    )
                )
                assert route.call_count == 2, "GFW endpoint must be called for both positive and negative dark-vessel checks."

        dark_positive = assess_dark_vessel(detections[0], pos_records)
        dark_negative = assess_dark_vessel(detections[1], neg_records)
        assert dark_positive.dark_vessel is True, "Detection with no nearby AIS records must be flagged as a dark vessel."
        assert dark_negative.dark_vessel is False, "Detection with nearby AIS support must not be flagged as a dark vessel."

        qdrant_host = qdrant.get_container_host_ip()
        qdrant_port = qdrant.get_exposed_port(6333)
        qdrant_url = f"http://{qdrant_host}:{qdrant_port}"
        qdrant_client = _wait_for_qdrant(qdrant_url)
        qdrant_collection = "e2e_similarity"

        if qdrant_client.collection_exists(qdrant_collection):
            qdrant_client.delete_collection(qdrant_collection)
        qdrant_client.create_collection(
            collection_name=qdrant_collection,
            vectors_config=qmodels.VectorParams(size=4, distance=qmodels.Distance.COSINE),
        )
        qdrant_client.upsert(
            collection_name=qdrant_collection,
            points=[
                qmodels.PointStruct(
                    id=1,
                    vector=[0.11, 0.21, 0.31, 0.41],
                    payload={"patch_id": detections[0].patch_id},
                )
            ],
            wait=True,
        )
        qdrant_result = qdrant_client.query_points(
            collection_name=qdrant_collection,
            query=[0.10, 0.20, 0.30, 0.40],
            limit=3,
            with_payload=True,
        )
        qdrant_hits = getattr(qdrant_result, "points", qdrant_result)
        assert len(qdrant_hits) >= 1, "Qdrant similarity search must return at least one result after inserting a fake embedding."

        is_dark_map = {
            detections[0].patch_id: dark_positive.dark_vessel,
            detections[1].patch_id: dark_negative.dark_vessel,
            detections[2].patch_id: False,
        }
        _seed_postgres(sync_db_url, detections, is_dark_map)

        main_module = importlib.import_module("dashboard.backend.main")
        main_module = importlib.reload(main_module)
        monkeypatch.setattr(main_module, "detection_poller", _idle_poller)

        with TestClient(main_module.app) as client:
            all_resp = client.get("/api/detections", params={"min_confidence": 0.5})
            assert all_resp.status_code == 200, "Detections endpoint must return HTTP 200 for a valid filter request."
            all_payload = all_resp.json()
            assert all_payload["total"] == 3, "Filtering with min_confidence=0.5 must keep all three inserted detections."

            dark_resp = client.get("/api/detections", params={"dark_only": "true", "min_confidence": 0.0})
            assert dark_resp.status_code == 200, "Detections endpoint must return HTTP 200 for dark_only filter requests."
            dark_payload = dark_resp.json()
            assert dark_payload["total"] == 1, "dark_only filtering must return exactly one dark-vessel detection."
            assert dark_payload["items"][0]["is_dark"] is True, "dark_only result entries must have is_dark=true."

            paged_resp = client.get("/api/detections", params={"page": 1, "page_size": 2})
            assert paged_resp.status_code == 200, "Detections endpoint must support pagination parameters."
            paged_payload = paged_resp.json()
            assert len(paged_payload["items"]) == 2, "page_size=2 must limit detections response to two items."

        row_count = _count_postgres_rows(sync_db_url)
        assert row_count == 3, "Postgres must contain exactly three detection rows after e2e pipeline insertion."
