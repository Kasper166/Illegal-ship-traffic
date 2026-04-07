from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import rasterio
from pydantic import BaseModel, Field
from rasterio.features import rasterize
from rasterio.warp import transform_bounds, transform_geom
from rasterio.windows import Window
from scipy.ndimage import gaussian_filter
import typer

from shared.logging import get_logger

logger = get_logger("ingestion.preprocessor")
app = typer.Typer(help="Windowed Sentinel-1 GRD preprocessor.")


class PatchMetadata(BaseModel):
    patch_path: str
    geojson_path: str
    scene_id: str
    patch_index: int
    window: tuple[int, int, int, int]
    bounds_wgs84: list[float]
    land_fraction: float
    percentile_min: float
    percentile_max: float


class PreprocessingResult(BaseModel):
    scene_id: str
    source_safe_dir: str
    output_dir: str
    patch_paths: list[str]
    metadata: list[PatchMetadata]
    total_windows: int
    kept_patches: int
    land_skipped: int
    quality_flag: str = Field(
        description="ok if >=1 patches kept and keep ratio >= 20%, else low_coverage"
    )


def _find_measurement_tiff(safe_dir: Path) -> Path:
    measurement_dir = safe_dir / "measurement"
    if not measurement_dir.exists():
        raise FileNotFoundError(f"Missing measurement directory in SAFE: {safe_dir}")
    candidates = sorted(measurement_dir.glob("*.tif")) + sorted(
        measurement_dir.glob("*.tiff")
    )
    if not candidates:
        raise FileNotFoundError(f"No TIFF measurements found in: {measurement_dir}")
    return candidates[0]


def _load_land_geometries_wgs84(mask_geojson_path: Path) -> list[dict[str, Any]]:
    with mask_geojson_path.open("r", encoding="utf-8") as f:
        payload = json.load(f)
    geoms: list[dict[str, Any]] = []
    if payload.get("type") == "FeatureCollection":
        for feat in payload.get("features", []):
            geom = feat.get("geometry")
            if geom:
                geoms.append(geom)
    elif payload.get("type") in {"Polygon", "MultiPolygon"}:
        geoms.append(payload)
    else:
        raise ValueError("Unsupported coastline mask GeoJSON format.")
    return geoms


def _gaussian_denoise_window(tile: np.ndarray, sigma: float = 1.0) -> np.ndarray:
    tile = tile.astype(np.float32, copy=False)
    if tile.size == 0:
        return tile
    try:
        # Keeps memory bounded per tile and avoids SAR-specific heavy dependencies.
        return cv2.GaussianBlur(tile, ksize=(0, 0), sigmaX=sigma, sigmaY=sigma)
    except Exception:
        return gaussian_filter(tile, sigma=sigma)


def _sigma_naught_db(tile: np.ndarray, eps: float = 1e-6) -> np.ndarray:
    power = np.square(tile.astype(np.float32))
    sigma0_db = 10.0 * np.log10(np.maximum(power, eps))
    return sigma0_db.astype(np.float32)


def _normalize_percentile(tile: np.ndarray, p2: float = 2, p98: float = 98) -> tuple[np.ndarray, float, float]:
    lo = float(np.percentile(tile, p2))
    hi = float(np.percentile(tile, p98))
    if hi <= lo:
        return np.zeros_like(tile, dtype=np.float32), lo, hi
    clipped = np.clip(tile, lo, hi)
    norm = (clipped - lo) / (hi - lo)
    return norm.astype(np.float32), lo, hi


def _window_bbox_geojson(ds: rasterio.DatasetReader, window: Window) -> dict[str, Any]:
    left, bottom, right, top = rasterio.windows.bounds(window, ds.transform)
    wgs84_bounds = transform_bounds(ds.crs, "EPSG:4326", left, bottom, right, top)
    minx, miny, maxx, maxy = wgs84_bounds
    return {
        "type": "Feature",
        "properties": {},
        "geometry": {
            "type": "Polygon",
            "coordinates": [
                [
                    [minx, miny],
                    [maxx, miny],
                    [maxx, maxy],
                    [minx, maxy],
                    [minx, miny],
                ]
            ],
        },
    }


def _land_fraction_for_window(
    window: Window,
    ds: rasterio.DatasetReader,
    land_geometries_in_raster_crs: list[dict[str, Any]],
) -> float:
    if not land_geometries_in_raster_crs:
        return 0.0
    h = int(window.height)
    w = int(window.width)
    if h <= 0 or w <= 0:
        return 1.0
    window_transform = rasterio.windows.transform(window, ds.transform)
    land_mask = rasterize(
        [(geom, 1) for geom in land_geometries_in_raster_crs],
        out_shape=(h, w),
        transform=window_transform,
        fill=0,
        all_touched=False,
        dtype=np.uint8,
    )
    return float(land_mask.mean())


def preprocess_safe_scene(
    safe_dir: Path,
    output_dir: Path,
    coastline_mask_geojson: Path,
    tile_size: int = 512,
    overlap: int = 64,
    land_skip_threshold: float = 0.6,
) -> PreprocessingResult:
    safe_dir = safe_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    scene_id = safe_dir.name.replace(".SAFE", "")
    scene_output = output_dir / scene_id
    scene_output.mkdir(parents=True, exist_ok=True)

    measurement_tif = _find_measurement_tiff(safe_dir)
    wgs84_land_geometries = _load_land_geometries_wgs84(coastline_mask_geojson)

    patch_paths: list[str] = []
    metadata: list[PatchMetadata] = []
    total_windows = 0
    land_skipped = 0
    patch_idx = 0

    with rasterio.open(measurement_tif) as ds:
        land_geometries_in_raster_crs = [
            transform_geom("EPSG:4326", ds.crs, geom, precision=6)
            for geom in wgs84_land_geometries
        ]

        stride = tile_size - overlap
        if stride <= 0:
            raise ValueError("overlap must be smaller than tile_size.")

        for row_off in range(0, ds.height, stride):
            for col_off in range(0, ds.width, stride):
                win_w = min(tile_size, ds.width - col_off)
                win_h = min(tile_size, ds.height - row_off)
                if win_w < tile_size or win_h < tile_size:
                    continue

                total_windows += 1
                window = Window(col_off=col_off, row_off=row_off, width=win_w, height=win_h)

                land_fraction = _land_fraction_for_window(
                    window, ds, land_geometries_in_raster_crs
                )
                if land_fraction > land_skip_threshold:
                    land_skipped += 1
                    continue

                tile = ds.read(1, window=window, out_dtype="float32")
                tile = _gaussian_denoise_window(tile, sigma=1.0)
                sigma0_db = _sigma_naught_db(tile)
                normalized, pmin, pmax = _normalize_percentile(sigma0_db)

                patch_png = scene_output / f"patch_{patch_idx:06d}.png"
                patch_geojson = scene_output / f"patch_{patch_idx:06d}.geojson"

                # PNG stores uint8; normalized processing remains float32 in-memory.
                png_arr = np.clip(normalized * 255.0, 0, 255).astype(np.uint8)
                ok = cv2.imwrite(str(patch_png), png_arr)
                if not ok:
                    raise RuntimeError(f"Failed writing patch PNG: {patch_png}")

                bbox_feature = _window_bbox_geojson(ds, window)
                with patch_geojson.open("w", encoding="utf-8") as f:
                    json.dump(bbox_feature, f)

                bounds_wgs84 = transform_bounds(
                    ds.crs,
                    "EPSG:4326",
                    *rasterio.windows.bounds(window, ds.transform),
                )
                meta = PatchMetadata(
                    patch_path=str(patch_png),
                    geojson_path=str(patch_geojson),
                    scene_id=scene_id,
                    patch_index=patch_idx,
                    window=(int(col_off), int(row_off), int(win_w), int(win_h)),
                    bounds_wgs84=[float(v) for v in bounds_wgs84],
                    land_fraction=land_fraction,
                    percentile_min=pmin,
                    percentile_max=pmax,
                )
                metadata.append(meta)
                patch_paths.append(str(patch_png))
                patch_idx += 1

    keep_ratio = (len(patch_paths) / total_windows) if total_windows else 0.0
    quality_flag = "ok" if patch_paths and keep_ratio >= 0.2 else "low_coverage"

    logger.info(
        "Preprocessed scene=%s patches=%s land_mask_skips=%s total_windows=%s",
        scene_id,
        len(patch_paths),
        land_skipped,
        total_windows,
    )

    return PreprocessingResult(
        scene_id=scene_id,
        source_safe_dir=str(safe_dir),
        output_dir=str(scene_output),
        patch_paths=patch_paths,
        metadata=metadata,
        total_windows=total_windows,
        kept_patches=len(patch_paths),
        land_skipped=land_skipped,
        quality_flag=quality_flag,
    )


@app.command("run")
def run_cli(
    safe_dir: Path = typer.Option(..., "--safe-dir", help="Path to Sentinel-1 GRD .SAFE directory."),
    output_dir: Path = typer.Option(
        Path(os.getenv("DATA_DIR", "/app/data")) / "patches",
        "--output-dir",
        help="Patch output directory.",
    ),
    coastline_mask_geojson: Path = typer.Option(
        ...,
        "--coastline-mask",
        help="GSHHG coastline mask as WGS84 GeoJSON.",
    ),
    tile_size: int = typer.Option(512, "--tile-size"),
    overlap: int = typer.Option(64, "--overlap"),
    land_skip_threshold: float = typer.Option(0.6, "--land-skip-threshold"),
) -> None:
    result = preprocess_safe_scene(
        safe_dir=safe_dir,
        output_dir=output_dir,
        coastline_mask_geojson=coastline_mask_geojson,
        tile_size=tile_size,
        overlap=overlap,
        land_skip_threshold=land_skip_threshold,
    )
    typer.echo(result.model_dump_json(indent=2))


if __name__ == "__main__":
    app()
