from __future__ import annotations

import json
import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import typer
from label_studio_sdk import Client

from shared.logging import get_logger
from shared.schemas import DetectionRecord

logger = get_logger("active_learning.router")
app = typer.Typer(help="Route low-confidence detections into Label Studio.")


@dataclass(frozen=True)
class QueueRow:
    detection_id: str
    confidence: float
    patch_path: str
    bbox_xyxy: list[float]
    class_label: str


def _connect_queue_db(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS labeling_queue (
            task_id INTEGER,
            detection_id TEXT PRIMARY KEY,
            status TEXT NOT NULL,
            annotator TEXT,
            created_at TEXT NOT NULL,
            completed_at TEXT
        )
        """
    )
    conn.commit()
    return conn


def _queue_has_detection(conn: sqlite3.Connection, detection_id: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM labeling_queue WHERE detection_id = ? LIMIT 1", (detection_id,)
    ).fetchone()
    return row is not None


def _insert_queue_row(
    conn: sqlite3.Connection,
    *,
    task_id: int | None,
    detection_id: str,
    status: str = "pending",
    annotator: str | None = None,
    completed_at: str | None = None,
) -> None:
    conn.execute(
        """
        INSERT OR REPLACE INTO labeling_queue (
            task_id, detection_id, status, annotator, created_at, completed_at
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            task_id,
            detection_id,
            status,
            annotator,
            datetime.now(timezone.utc).isoformat(),
            completed_at,
        ),
    )
    conn.commit()


def _detection_id(scene_id: str, patch_id: str, idx: int) -> str:
    return f"{scene_id}:{patch_id}:{idx}"


def _load_detections(detections_jsonl: Path) -> list[DetectionRecord]:
    out: list[DetectionRecord] = []
    with detections_jsonl.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            out.append(DetectionRecord.model_validate_json(line))
    return out


def _xyxy_to_ls_rectangle(
    xyxy: list[float], image_width: int = 512, image_height: int = 512
) -> dict[str, Any]:
    x1, y1, x2, y2 = xyxy
    w = max(0.0, x2 - x1)
    h = max(0.0, y2 - y1)
    return {
        "x": (x1 / image_width) * 100.0,
        "y": (y1 / image_height) * 100.0,
        "width": (w / image_width) * 100.0,
        "height": (h / image_height) * 100.0,
        "rotation": 0,
    }


def _build_task_payload(patch_path: str, det: DetectionRecord) -> dict[str, Any]:
    return {
        "data": {
            "image": patch_path,
            "patch_id": det.patch_id,
            "scene_id": det.scene_id,
            "confidence": det.confidence,
        },
        "predictions": [
            {
                "model_version": "darkwater-baseline",
                "score": float(det.confidence),
                "result": [
                    {
                        "id": f"pred-{det.patch_id}",
                        "from_name": "label",
                        "to_name": "image",
                        "type": "rectanglelabels",
                        "value": {
                            **_xyxy_to_ls_rectangle(det.bbox_xyxy),
                            "rectanglelabels": [det.class_label],
                        },
                    }
                ],
            }
        ],
    }


def push_for_review(
    *,
    detections_jsonl: Path,
    patches_root: Path,
    project_id: int,
    queue_db_path: Path,
    dry_run: bool = False,
) -> int:
    detections = _load_detections(detections_jsonl)
    filtered = [d for d in detections if d.flagged_for_review]
    filtered.sort(key=lambda d: d.confidence)  # least confidence sampling

    conn = _connect_queue_db(queue_db_path)

    queued: list[QueueRow] = []
    for idx, det in enumerate(filtered):
        detection_id = _detection_id(det.scene_id, det.patch_id, idx)
        if _queue_has_detection(conn, detection_id):
            continue
        patch_path = str(patches_root / det.scene_id / f"{det.patch_id}.png")
        queued.append(
            QueueRow(
                detection_id=detection_id,
                confidence=det.confidence,
                patch_path=patch_path,
                bbox_xyxy=det.bbox_xyxy,
                class_label=det.class_label,
            )
        )

    if dry_run:
        for row in queued:
            logger.info(
                "[dry-run] would push detection_id=%s confidence=%.4f patch=%s",
                row.detection_id,
                row.confidence,
                row.patch_path,
            )
        conn.close()
        return len(queued)

    ls_url = os.getenv("LABEL_STUDIO_URL", "http://label-studio:8080")
    ls_token = os.getenv("LABEL_STUDIO_TOKEN")
    if not ls_token:
        raise ValueError("LABEL_STUDIO_TOKEN is required when dry_run is False.")
    client = Client(url=ls_url, api_key=ls_token)
    project = client.get_project(project_id)

    pushed = 0
    for row in queued:
        fake_det = DetectionRecord(
            patch_id=row.detection_id.split(":")[1],
            tile_id=row.detection_id.split(":")[1],
            bbox_xyxy=row.bbox_xyxy,
            pixel_coords=row.bbox_xyxy,
            confidence=row.confidence,
            class_label=row.class_label,
            lat_lon_center=(0.0, 0.0),
            timestamp=datetime.now(timezone.utc),
            scene_id=row.detection_id.split(":")[0],
            flagged_for_review=True,
            is_dark=False,
        )
        payload = _build_task_payload(row.patch_path, fake_det)
        created = project.import_tasks([payload])
        task_id = None
        if created and isinstance(created, list) and isinstance(created[0], dict):
            task_id = int(created[0].get("id")) if created[0].get("id") else None
        _insert_queue_row(
            conn,
            task_id=task_id,
            detection_id=row.detection_id,
            status="pending",
        )
        pushed += 1

    conn.close()
    logger.info("Pushed %s tasks to Label Studio project=%s", pushed, project_id)
    return pushed


def _xywh_pct_to_xyxy_pixels(
    x_pct: float,
    y_pct: float,
    w_pct: float,
    h_pct: float,
    image_w: int = 512,
    image_h: int = 512,
) -> tuple[float, float, float, float]:
    x1 = (x_pct / 100.0) * image_w
    y1 = (y_pct / 100.0) * image_h
    w = (w_pct / 100.0) * image_w
    h = (h_pct / 100.0) * image_h
    return x1, y1, x1 + w, y1 + h


def _xyxy_to_yolo_line(xyxy: tuple[float, float, float, float], class_id: int, img_w: int = 512, img_h: int = 512) -> str:
    x1, y1, x2, y2 = xyxy
    w = max(0.0, x2 - x1)
    h = max(0.0, y2 - y1)
    xc = x1 + w / 2.0
    yc = y1 + h / 2.0
    return (
        f"{class_id} "
        f"{xc / img_w:.6f} {yc / img_h:.6f} "
        f"{w / img_w:.6f} {h / img_h:.6f}"
    )


def pull_completed_labels(
    *,
    project_id: int,
    queue_db_path: Path,
    output_dir: Path,
) -> int:
    ls_url = os.getenv("LABEL_STUDIO_URL", "http://label-studio:8080")
    ls_token = os.getenv("LABEL_STUDIO_TOKEN")
    if not ls_token:
        raise ValueError("LABEL_STUDIO_TOKEN is required.")

    class_map = {"fishing": 0, "non-fishing": 1}
    output_dir.mkdir(parents=True, exist_ok=True)
    conn = _connect_queue_db(queue_db_path)

    client = Client(url=ls_url, api_key=ls_token)
    project = client.get_project(project_id)
    tasks = project.get_tasks()

    written = 0
    for task in tasks:
        annotations = task.get("annotations") or []
        if not annotations:
            continue
        # Use first completed annotation.
        ann = annotations[0]
        if not ann.get("result"):
            continue

        patch_id = str(task.get("data", {}).get("patch_id", "unknown_patch"))
        scene_id = str(task.get("data", {}).get("scene_id", "unknown_scene"))
        label_path = output_dir / f"{scene_id}__{patch_id}.txt"

        yolo_lines: list[str] = []
        for res in ann["result"]:
            if res.get("type") != "rectanglelabels":
                continue
            value = res.get("value", {})
            labels = value.get("rectanglelabels", [])
            if not labels:
                continue
            class_name = str(labels[0]).strip().lower()
            if class_name not in class_map:
                continue
            xyxy = _xywh_pct_to_xyxy_pixels(
                float(value.get("x", 0.0)),
                float(value.get("y", 0.0)),
                float(value.get("width", 0.0)),
                float(value.get("height", 0.0)),
            )
            yolo_lines.append(_xyxy_to_yolo_line(xyxy, class_map[class_name]))

        if not yolo_lines:
            continue

        label_path.write_text("\n".join(yolo_lines) + "\n", encoding="utf-8")
        written += 1

        task_id = task.get("id")
        detection_id = None
        if scene_id != "unknown_scene" and patch_id != "unknown_patch":
            detection_id = f"{scene_id}:{patch_id}:0"
        if detection_id:
            _insert_queue_row(
                conn,
                task_id=int(task_id) if task_id else None,
                detection_id=detection_id,
                status="complete",
                annotator=str(ann.get("completed_by") or ""),
                completed_at=datetime.now(timezone.utc).isoformat(),
            )

    conn.close()
    logger.info("Pulled %s completed label files to %s", written, output_dir)
    return written


@app.command("push")
def push_cli(
    detections_jsonl: Path = typer.Option(..., "--detections-jsonl"),
    patches_root: Path = typer.Option(..., "--patches-root"),
    project_id: int = typer.Option(..., "--project-id"),
    queue_db_path: Path = typer.Option(
        Path(os.getenv("LABELING_QUEUE_DB", "/app/data/labeling_queue.sqlite")),
        "--queue-db-path",
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Print tasks without API calls."),
) -> None:
    count = push_for_review(
        detections_jsonl=detections_jsonl,
        patches_root=patches_root,
        project_id=project_id,
        queue_db_path=queue_db_path,
        dry_run=dry_run,
    )
    typer.echo(f"Prepared/Pushed {count} task(s).")


@app.command("pull")
def pull_cli(
    project_id: int = typer.Option(..., "--project-id"),
    queue_db_path: Path = typer.Option(
        Path(os.getenv("LABELING_QUEUE_DB", "/app/data/labeling_queue.sqlite")),
        "--queue-db-path",
    ),
    output_dir: Path = typer.Option(
        Path(__file__).resolve().parent / "corrected_labels",
        "--output-dir",
    ),
) -> None:
    count = pull_completed_labels(
        project_id=project_id,
        queue_db_path=queue_db_path,
        output_dir=output_dir,
    )
    typer.echo(f"Pulled {count} completed label file(s).")


if __name__ == "__main__":
    app()
