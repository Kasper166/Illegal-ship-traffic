from __future__ import annotations

import warnings
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest
import responses

from ingestion.downloader import (
    DataCoverageWarning,
    InsufficientStorageError,
    _healthcheck_copernicus,
    check_storage_quota,
    run_download,
)


class FakeSentinelAPI:
    def __init__(self, products: dict[str, dict[str, Any]], target_dir: Path) -> None:
        self._products = products
        self._target_dir = target_dir
        self.download_calls: list[str] = []

    def query(self, *args: Any, **kwargs: Any) -> dict[str, dict[str, Any]]:
        return self._products

    def download(self, product_id: str, directory_path: str) -> dict[str, Any]:
        self.download_calls.append(product_id)
        out_dir = Path(directory_path)
        out_dir.mkdir(parents=True, exist_ok=True)
        file_path = out_dir / f"{product_id}.zip"
        file_path.write_bytes(b"x" * 1024)
        return {"path": str(file_path)}


def test_run_download_skips_manifest_and_warns_on_cadence(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("COPERNICUS_CLIENT_ID", "client-id")
    monkeypatch.setenv("COPERNICUS_CLIENT_SECRET", "client-secret")
    monkeypatch.setenv("CDSE_ODATA_URL", "https://catalogue.dataspace.copernicus.test/odata/v1")

    data_dir = tmp_path / "data"
    manifest_path = tmp_path / "manifest.sqlite"

    products = {
        "uuid-1": {
            "title": "S1A_SCENE_1",
            "beginposition": datetime(2026, 1, 1, tzinfo=timezone.utc).isoformat(),
        },
        "uuid-2": {
            "title": "S1A_SCENE_2",
            "beginposition": datetime(2026, 1, 10, tzinfo=timezone.utc).isoformat(),
        },
    }
    api = FakeSentinelAPI(products, data_dir)

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        downloaded_first = run_download(
            aoi_geojson={
                "type": "Polygon",
                "coordinates": [[[-5, -5], [10, -5], [10, 10], [-5, 10], [-5, -5]]],
            },
            data_dir=data_dir,
            manifest_path=manifest_path,
            expected_revisit_days=6,
            api=api,
        )

    assert sorted(downloaded_first) == ["S1A_SCENE_1", "S1A_SCENE_2"]
    assert len(api.download_calls) == 2
    assert any(issubclass(w.category, DataCoverageWarning) for w in caught)

    downloaded_second = run_download(
        aoi_geojson={
            "type": "Polygon",
            "coordinates": [[[-5, -5], [10, -5], [10, 10], [-5, 10], [-5, -5]]],
        },
        data_dir=data_dir,
        manifest_path=manifest_path,
        expected_revisit_days=6,
        api=api,
    )
    assert downloaded_second == []
    assert len(api.download_calls) == 2


@responses.activate
def test_healthcheck_uses_copernicus_url(monkeypatch) -> None:
    monkeypatch.setenv("CDSE_ODATA_URL", "https://catalogue.dataspace.copernicus.test/odata/v1")
    responses.add(
        responses.GET,
        "https://catalogue.dataspace.copernicus.test/odata/v1/Products?$top=1",
        status=200,
    )
    assert _healthcheck_copernicus() == 200


def test_check_storage_quota_raises_when_low_space(tmp_path: Path, monkeypatch) -> None:
    class _DU:
        total = 100
        used = 95
        free = 5 * 1024 * 1024 * 1024

    monkeypatch.setattr("ingestion.downloader.shutil.disk_usage", lambda _: _DU)
    with pytest.raises(InsufficientStorageError):
        check_storage_quota(tmp_path, min_free_gb=20)
