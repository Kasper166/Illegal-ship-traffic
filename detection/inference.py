from __future__ import annotations

import argparse
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import wandb
from ultralytics import YOLO

from shared.logging import get_logger
from shared.schemas import DetectionRecord as Detection
from shared.storage import download_file, list_keys

logger = get_logger("detection.inference")


def _load_patch_bbox_geojson(geojson_path: Path) -> list[list[float]]:
    payload = json.loads(geojson_path.read_text(encoding="utf-8"))
    coords = payload.get("geometry", {}).get("coordinates", [])
    if not coords or not coords[0]:
        raise ValueError(f"Invalid bbox geojson coordinates in {geojson_path}")
    return coords[0]


def _bbox_to_minmax_latlon(poly_coords: list[list[float]]) -> tuple[float, float, float, float]:
    xs = [float(pt[0]) for pt in poly_coords]
    ys = [float(pt[1]) for pt in poly_coords]
    return min(xs), min(ys), max(xs), max(ys)


def _pixel_center_to_latlon(
    bbox_xyxy: list[float],
    img_w: int,
    img_h: int,
    min_lon: float,
    min_lat: float,
    max_lon: float,
    max_lat: float,
) -> tuple[float, float]:
    x1, y1, x2, y2 = bbox_xyxy
    cx = (x1 + x2) / 2.0
    cy = (y1 + y2) / 2.0
    lon = min_lon + (cx / float(img_w)) * (max_lon - min_lon)
    # image y grows downward; latitude grows upward
    lat = max_lat - (cy / float(img_h)) * (max_lat - min_lat)
    return (lat, lon)


def _sync_patches_from_r2(scene_id: str, patches_dir: Path) -> None:
    """Download any patches for scene_id not already present locally."""
    prefix = f"patches/{scene_id}/"
    try:
        keys = list_keys(prefix)
    except Exception as exc:
        logger.warning("Could not list R2 keys for prefix %s: %s", prefix, exc)
        return
    for key in keys:
        local = patches_dir / scene_id / Path(key).name
        if not local.exists():
            download_file(key, local)


def run_inference(
    patches_dir: Path,
    model_path: Path,
    output_jsonl: Path,
    batch_size: int = 16,
    scene_id: str | None = None,
) -> Path:
    if scene_id and os.getenv("R2_ENDPOINT_URL"):
        _sync_patches_from_r2(scene_id, patches_dir)

    threshold = float(os.getenv("ACTIVE_LEARNING_THRESHOLD", "0.45"))
    device = os.getenv("INFERENCE_DEVICE", "cpu")

    run = wandb.init(
        project=os.getenv("WANDB_PROJECT", "darkwater"),
        entity=os.getenv("WANDB_ENTITY"),
        tags=["darkwater", "sar", "baseline"],
        name=os.getenv("WANDB_RUN_NAME", "inference"),
        reinit=True,
        config={
            "model_path": str(model_path),
            "patches_dir": str(patches_dir),
            "batch_size": batch_size,
            "threshold": threshold,
            "device": device,
        },
    )

    image_paths = sorted(
        [
            p
            for p in patches_dir.rglob("*")
            if p.suffix.lower() in {".png", ".jpg", ".jpeg", ".tif", ".tiff"}
        ]
    )
    if not image_paths:
        raise FileNotFoundError(f"No patch images found in {patches_dir}")

    output_jsonl.parent.mkdir(parents=True, exist_ok=True)

    model = YOLO(str(model_path))
    class_names: dict[int, str] = {}
    if hasattr(model, "names") and isinstance(model.names, dict):
        class_names = {int(k): str(v) for k, v in model.names.items()}

    total_patches = len(image_paths)
    total_detections = 0
    started = time.perf_counter()

    with output_jsonl.open("w", encoding="utf-8") as out:
        for i in range(0, total_patches, batch_size):
            batch = image_paths[i : i + batch_size]
            results = model.predict(
                source=[str(p) for p in batch],
                conf=0.01,
                device=device,
                verbose=False,
            )
            for img_path, result in zip(batch, results):
                geojson_path = img_path.with_suffix(".geojson")
                if not geojson_path.exists():
                    logger.warning("Missing patch geojson for %s; skipping detections.", img_path)
                    continue

                poly = _load_patch_bbox_geojson(geojson_path)
                min_lon, min_lat, max_lon, max_lat = _bbox_to_minmax_latlon(poly)
                scene_id = img_path.parent.name
                patch_id = img_path.stem
                tile_id = patch_id

                img_h = int(result.orig_shape[0])
                img_w = int(result.orig_shape[1])
                boxes = result.boxes
                if boxes is None:
                    continue

                for box in boxes:
                    xyxy = box.xyxy[0].tolist()
                    conf = float(box.conf[0].item())
                    cls_idx = int(box.cls[0].item())
                    label = class_names.get(cls_idx, str(cls_idx))
                    lat_lon = _pixel_center_to_latlon(
                        bbox_xyxy=xyxy,
                        img_w=img_w,
                        img_h=img_h,
                        min_lon=min_lon,
                        min_lat=min_lat,
                        max_lon=max_lon,
                        max_lat=max_lat,
                    )
                    det = Detection(
                        patch_id=patch_id,
                        tile_id=tile_id,
                        bbox_xyxy=[float(v) for v in xyxy],
                        pixel_coords=[float(v) for v in xyxy],
                        confidence=conf,
                        class_label=label,
                        lat_lon_center=lat_lon,
                        timestamp=datetime.now(timezone.utc),
                        scene_id=scene_id,
                        flagged_for_review=conf < threshold,
                        is_dark=False,
                    )
                    out.write(det.model_dump_json() + "\n")
                    total_detections += 1

    elapsed = max(1e-9, time.perf_counter() - started)
    throughput = total_patches / elapsed
    logger.info(
        "Inference complete patches=%s detections=%s throughput=%.2f patches/sec output=%s",
        total_patches,
        total_detections,
        throughput,
        output_jsonl,
    )
    wandb.log(
        {
            "inference/patches_total": total_patches,
            "inference/detections_total": total_detections,
            "inference/throughput_patches_per_sec": throughput,
        }
    )
    wandb.save(str(output_jsonl))
    run.finish()
    return output_jsonl


def main() -> None:
    parser = argparse.ArgumentParser(description="Run YOLOv8 batch inference on SAR patches.")
    parser.add_argument("patches_dir", type=Path, help="Directory containing preprocessed patch images.")
    parser.add_argument("model_path", type=Path, help="Path to YOLOv8 checkpoint.")
    parser.add_argument(
        "--output-jsonl",
        type=Path,
        default=Path(__file__).resolve().parent / "detections.jsonl",
        help="Output JSONL path for detections.",
    )
    parser.add_argument("--batch-size", type=int, default=16, help="Batch size for model inference.")
    args = parser.parse_args()
    run_inference(
        patches_dir=args.patches_dir,
        model_path=args.model_path,
        output_jsonl=args.output_jsonl,
        batch_size=args.batch_size,
    )


if __name__ == "__main__":
    main()
