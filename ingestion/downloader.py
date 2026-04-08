from __future__ import annotations

import json
import os
import shutil
import sqlite3
import warnings
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests
import typer
from sentinelsat import geojson_to_wkt

from shared.logging import get_logger
from shared.storage import object_exists, upload_file

logger = get_logger("ingestion.downloader")
app = typer.Typer(help="Sentinel-1 ingestion CLI for DARKWATER.")

DEFAULT_AOI_GEOJSON = {
    "type": "Polygon",
    "coordinates": [
        [
            [-5.0, -5.0],
            [10.0, -5.0],
            [10.0, 10.0],
            [-5.0, 10.0],
            [-5.0, -5.0],
        ]
    ],
}


class DataCoverageWarning(UserWarning):
    """Raised when observed revisit cadence is worse than expected."""


class InsufficientStorageError(RuntimeError):
    """Raised when host free storage is below required threshold."""


@dataclass(frozen=True)
class ProductRecord:
    product_id: str
    scene_id: str
    acquisition_time: datetime


class CDSEODataAPI:
    """Minimal CDSE OData API client with sentinelsat-compatible methods."""

    def __init__(
        self,
        *,
        client_id: str,
        client_secret: str,
        token_url: str,
        odata_url: str,
    ) -> None:
        self.client_id = client_id
        self.client_secret = client_secret
        self.token_url = token_url.rstrip("/")
        self.odata_url = odata_url.rstrip("/")
        self._access_token: str | None = None
        self._token_expires_at: datetime | None = None

    def _get_token(self) -> str:
        now = datetime.now(timezone.utc)
        if self._access_token and self._token_expires_at and now < self._token_expires_at:
            return self._access_token
        resp = requests.post(
            self.token_url,
            data={
                "grant_type": "client_credentials",
                "client_id": self.client_id,
                "client_secret": self.client_secret,
            },
            timeout=30,
        )
        resp.raise_for_status()
        payload = resp.json()
        token = payload.get("access_token")
        if not token:
            raise RuntimeError("CDSE token response did not include access_token.")
        expires_in = int(payload.get("expires_in", 300))
        # Subtract 30 s as a safety buffer against clock skew and latency.
        self._token_expires_at = now + timedelta(seconds=max(0, expires_in - 30))
        self._access_token = str(token)
        return self._access_token

    def _invalidate_token(self) -> None:
        self._access_token = None
        self._token_expires_at = None

    def query(
        self,
        footprint_wkt: str,
        *,
        date: tuple[datetime, datetime],
        platformname: str,
        producttype: str,
    ) -> dict[str, dict[str, Any]]:
        start, end = date
        filter_query = (
            f"Collection/Name eq '{platformname}'"
            f" and Attributes/OData.CSC.StringAttribute/any(a:a/Name eq 'productType'"
            f" and a/OData.CSC.StringAttribute/Value eq '{producttype}')"
            f" and ContentDate/Start ge {start.strftime('%Y-%m-%dT%H:%M:%S.000Z')}"
            f" and ContentDate/Start le {end.strftime('%Y-%m-%dT%H:%M:%S.000Z')}"
            f" and OData.CSC.Intersects(area=geography'SRID=4326;{footprint_wkt}')"
        )
        params = {"$filter": filter_query, "$top": 100, "$orderby": "ContentDate/Start asc"}
        resp = requests.get(
            f"{self.odata_url}/Products",
            params=params,
            headers={"Authorization": f"Bearer {self._get_token()}"},
            timeout=60,
        )
        if resp.status_code == 401:
            self._invalidate_token()
            resp = requests.get(
                f"{self.odata_url}/Products",
                params=params,
                headers={"Authorization": f"Bearer {self._get_token()}"},
                timeout=60,
            )
        resp.raise_for_status()
        values = resp.json().get("value", [])
        out: dict[str, dict[str, Any]] = {}
        for item in values:
            product_id = str(item.get("Id"))
            out[product_id] = {
                "title": item.get("Name", product_id),
                "beginposition": item.get("ContentDate", {}).get("Start"),
                "uuid": product_id,
            }
        return out

    def download(self, product_id: str, directory_path: str) -> dict[str, Any]:
        url = f"{self.odata_url}/Products({product_id})/$value"
        output = Path(directory_path) / f"{product_id}.zip"
        output.parent.mkdir(parents=True, exist_ok=True)
        for attempt in range(2):
            with requests.get(
                url,
                headers={"Authorization": f"Bearer {self._get_token()}"},
                stream=True,
                timeout=180,
            ) as resp:
                if resp.status_code == 401 and attempt == 0:
                    self._invalidate_token()
                    continue
                resp.raise_for_status()
                with output.open("wb") as f:
                    for chunk in resp.iter_content(chunk_size=1024 * 1024):
                        if chunk:
                            f.write(chunk)
            break
        return {"path": str(output)}


def _load_aoi_geojson(path: Path | None) -> dict[str, Any]:
    if path is None:
        return DEFAULT_AOI_GEOJSON
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise ValueError(f"Missing required environment variable: {name}")
    return value


def _connect_manifest(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS downloads (
            scene_id TEXT PRIMARY KEY,
            product_id TEXT NOT NULL,
            downloaded_at TEXT NOT NULL,
            acquisition_time TEXT NOT NULL,
            file_size_bytes INTEGER NOT NULL,
            file_path TEXT NOT NULL
        )
        """
    )
    conn.commit()
    return conn


def _scene_exists(conn: sqlite3.Connection, scene_id: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM downloads WHERE scene_id = ? LIMIT 1", (scene_id,)
    ).fetchone()
    return row is not None


def _insert_download(
    conn: sqlite3.Connection,
    *,
    scene_id: str,
    product_id: str,
    acquisition_time: datetime,
    file_size_bytes: int,
    file_path: str,
) -> None:
    conn.execute(
        """
        INSERT INTO downloads (
            scene_id, product_id, downloaded_at, acquisition_time, file_size_bytes, file_path
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            scene_id,
            product_id,
            datetime.now(timezone.utc).isoformat(),
            acquisition_time.isoformat(),
            file_size_bytes,
            file_path,
        ),
    )
    conn.commit()


def _extract_products(products: dict[str, dict[str, Any]]) -> list[ProductRecord]:
    records: list[ProductRecord] = []
    for product_id, metadata in products.items():
        scene_id = (
            metadata.get("title")
            or metadata.get("identifier")
            or metadata.get("uuid")
            or product_id
        )
        raw_time = (
            metadata.get("beginposition")
            or metadata.get("ingestiondate")
            or metadata.get("datatakesensingstart")
        )
        if isinstance(raw_time, datetime):
            acq = raw_time
        elif isinstance(raw_time, str):
            acq = datetime.fromisoformat(raw_time.replace("Z", "+00:00"))
        else:
            acq = datetime.now(timezone.utc)
        records.append(
            ProductRecord(
                product_id=product_id,
                scene_id=scene_id,
                acquisition_time=acq.astimezone(timezone.utc),
            )
        )
    records.sort(key=lambda r: r.acquisition_time)
    return records


def _validate_revisit_cadence(
    records: list[ProductRecord], expected_days: int = 6
) -> None:
    if len(records) < 2:
        warnings.warn(
            "Insufficient Sentinel-1 scenes to validate revisit cadence for this window.",
            DataCoverageWarning,
            stacklevel=2,
        )
        return

    max_gap = max(
        (
            (records[i].acquisition_time - records[i - 1].acquisition_time).total_seconds()
            / 86400.0
        )
        for i in range(1, len(records))
    )
    if max_gap > expected_days:
        warnings.warn(
            (
                f"Observed Sentinel-1 revisit gap is {max_gap:.2f} days, "
                f"above expected {expected_days} days for Gulf of Guinea coverage."
            ),
            DataCoverageWarning,
            stacklevel=2,
        )


def _discover_file_size_bytes(download_result: dict[str, Any]) -> int:
    path = Path(str(download_result.get("path", "")))
    if path.exists():
        return path.stat().st_size
    size = download_result.get("size")
    if isinstance(size, int):
        return size
    return 0


def check_storage_quota(data_dir: Path, min_free_gb: int = 20) -> None:
    usage = shutil.disk_usage(data_dir)
    required_bytes = min_free_gb * 1024 * 1024 * 1024
    if usage.free < required_bytes:
        raise InsufficientStorageError(
            (
                f"Insufficient free storage in {data_dir}: "
                f"{usage.free / (1024 ** 3):.2f} GB available, "
                f"{min_free_gb} GB required."
            )
        )


def run_download(
    *,
    aoi_geojson: dict[str, Any],
    data_dir: Path,
    manifest_path: Path,
    expected_revisit_days: int = 6,
    api: Any | None = None,
    min_free_gb: int = 20,
) -> list[str]:
    data_dir.mkdir(parents=True, exist_ok=True)
    check_storage_quota(data_dir, min_free_gb=min_free_gb)
    conn = _connect_manifest(manifest_path)

    local_api = api or CDSEODataAPI(
        client_id=_env("COPERNICUS_CLIENT_ID"),
        client_secret=_env("COPERNICUS_CLIENT_SECRET"),
        token_url=os.getenv(
            "CDSE_TOKEN_URL",
            "https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token",
        ),
        odata_url=os.getenv("CDSE_ODATA_URL", "https://catalogue.dataspace.copernicus.eu/odata/v1"),
    )
    footprint_wkt = geojson_to_wkt(aoi_geojson)

    now = datetime.now(timezone.utc)
    start = now - timedelta(days=6)
    products = local_api.query(
        footprint_wkt,
        date=(start, now),
        platformname="Sentinel-1",
        producttype="GRD",
    )

    records = _extract_products(products)
    _validate_revisit_cadence(records, expected_days=expected_revisit_days)

    downloaded: list[str] = []
    for rec in records:
        if _scene_exists(conn, rec.scene_id):
            logger.info("Skipping already downloaded scene: %s", rec.scene_id)
            continue

        result = local_api.download(rec.product_id, directory_path=str(data_dir))
        file_size = _discover_file_size_bytes(result)
        file_path = str(result.get("path", ""))

        r2_key = f"scenes/{rec.scene_id}/{Path(file_path).name}"
        if file_path and Path(file_path).exists() and not object_exists(r2_key):
            upload_file(Path(file_path), r2_key)

        _insert_download(
            conn,
            scene_id=rec.scene_id,
            product_id=rec.product_id,
            acquisition_time=rec.acquisition_time,
            file_size_bytes=file_size,
            file_path=file_path,
        )
        logger.info(
            "Downloaded scene_id=%s timestamp=%s file_size_bytes=%s",
            rec.scene_id,
            datetime.now(timezone.utc).isoformat(),
            file_size,
        )
        downloaded.append(rec.scene_id)

    conn.close()
    return downloaded


@app.command("download")
def download_cli(
    aoi_geojson_path: Path | None = typer.Option(
        None,
        "--aoi-geojson",
        help="Optional AOI GeoJSON file. Defaults to Gulf of Guinea bbox.",
    ),
    data_dir: Path = typer.Option(
        Path(os.getenv("DATA_DIR", "/app/data")), "--data-dir", help="Download directory."
    ),
    manifest_path: Path = typer.Option(
        Path(os.getenv("INGESTION_MANIFEST_PATH", "/app/data/manifest.sqlite")),
        "--manifest-path",
        help="SQLite manifest path.",
    ),
    expected_revisit_days: int = typer.Option(
        6, "--expected-revisit-days", min=1, help="Expected revisit cadence in days."
    ),
    min_free_gb: int = typer.Option(
        20,
        "--min-free-gb",
        min=1,
        help="Minimum free host disk (GB) required before downloading.",
    ),
) -> None:
    aoi_geojson = _load_aoi_geojson(aoi_geojson_path)
    downloaded = run_download(
        aoi_geojson=aoi_geojson,
        data_dir=data_dir,
        manifest_path=manifest_path,
        expected_revisit_days=expected_revisit_days,
        min_free_gb=min_free_gb,
    )
    typer.echo(f"Downloaded {len(downloaded)} new scene(s).")


def _healthcheck_copernicus() -> int:
    """Small utility for tests/examples where direct HTTP mocking is useful."""
    odata_url = os.getenv("CDSE_ODATA_URL", "https://catalogue.dataspace.copernicus.eu/odata/v1")
    response = requests.get(f"{odata_url.rstrip('/')}/Products?$top=1", timeout=10)
    return response.status_code


if __name__ == "__main__":
    app()
