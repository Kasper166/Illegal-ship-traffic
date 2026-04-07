from __future__ import annotations

import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import typer
import wandb
import yaml
from pydantic import BaseModel

from active_learning.router import pull_completed_labels
from detection.train import train as train_yolo
from shared.logging import get_logger

logger = get_logger("active_learning.retrain")
app = typer.Typer(help="Active learning retraining loop for DARKWATER.")


class IterationRecord(BaseModel):
    iteration: int
    timestamp: str
    label_count: int
    map50: float
    promoted: bool


def _read_iterations(iterations_path: Path) -> list[IterationRecord]:
    if not iterations_path.exists():
        return []
    payload = json.loads(iterations_path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        return [IterationRecord.model_validate(item) for item in payload]
    if isinstance(payload, dict):
        rows = payload.get("iterations", [])
        return [IterationRecord.model_validate(item) for item in rows]
    return []


def _write_iterations(iterations_path: Path, rows: list[IterationRecord]) -> None:
    iterations_path.parent.mkdir(parents=True, exist_ok=True)
    iterations_path.write_text(
        json.dumps({"iterations": [r.model_dump() for r in rows]}, indent=2),
        encoding="utf-8",
    )


def _extract_patch_id(label_path: Path) -> str:
    stem = label_path.stem
    if "__" in stem:
        return stem.split("__", 1)[1]
    return stem


def _merge_corrected_labels(corrected_dir: Path, train_labels_dir: Path) -> int:
    train_labels_dir.mkdir(parents=True, exist_ok=True)
    corrected = sorted(corrected_dir.glob("*.txt"))
    if not corrected:
        return 0

    existing_index: dict[str, Path] = {}
    for existing in train_labels_dir.glob("*.txt"):
        existing_index[_extract_patch_id(existing)] = existing

    merged_count = 0
    for src in corrected:
        patch_id = _extract_patch_id(src)
        dst = existing_index.get(patch_id, train_labels_dir / f"{patch_id}.txt")
        shutil.copy2(src, dst)
        existing_index[patch_id] = dst
        merged_count += 1
    return merged_count


def _read_dataset_train_labels_dir(dataset_yaml: Path) -> Path:
    payload = yaml.safe_load(dataset_yaml.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Invalid dataset yaml format: {dataset_yaml}")
    path = payload.get("labels_train")
    if not path:
        # Fallback to env default if yaml does not include labels path.
        path = os.getenv("TRAIN_LABELS_DIR", "data/labels/train")
    path_obj = Path(str(path))
    if not path_obj.is_absolute():
        path_obj = (dataset_yaml.parent / path_obj).resolve()
    return path_obj


def _promote_model(best_checkpoint: Path, active_checkpoint: Path) -> None:
    active_checkpoint.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(best_checkpoint, active_checkpoint)


def retrain_iteration(
    *,
    project_id: int,
    dataset_yaml: Path,
    queue_db_path: Path,
    corrected_labels_dir: Path,
    iterations_path: Path,
    min_new_labels_to_retrain: int = 100,
    freeze_backbone: bool = True,
    freeze_layers: int = 10,
) -> IterationRecord:
    started = datetime.now(timezone.utc)
    pulled_count = pull_completed_labels(
        project_id=project_id,
        queue_db_path=queue_db_path,
        output_dir=corrected_labels_dir,
    )

    train_labels_dir = _read_dataset_train_labels_dir(dataset_yaml)
    merged_count = _merge_corrected_labels(corrected_labels_dir, train_labels_dir)
    label_count = len(list(train_labels_dir.glob("*.txt")))

    iterations = _read_iterations(iterations_path)
    previous = iterations[-1] if iterations else None
    prev_map50 = previous.map50 if previous else 0.0
    new_map50 = prev_map50
    best_checkpoint = Path("")

    should_retrain = pulled_count >= min_new_labels_to_retrain
    if should_retrain:
        report_path = train_yolo(
            dataset_yaml,
            freeze_backbone=freeze_backbone,
            freeze_layers=freeze_layers,
        )
        report = json.loads(report_path.read_text(encoding="utf-8"))
        new_map50 = float(report.get("map50", 0.0))
        best_checkpoint = Path(str(report.get("best_checkpoint", "")))
    else:
        logger.info(
            "Skipping retrain: pulled labels=%s below gate=%s",
            pulled_count,
            min_new_labels_to_retrain,
        )

    prev_map50 = previous.map50 if previous else 0.0
    prev_label_count = previous.label_count if previous else 0
    map_delta = new_map50 - prev_map50
    label_count_delta = label_count - prev_label_count

    if previous:
        prev_ts = datetime.fromisoformat(previous.timestamp)
        elapsed_h = max(
            1e-9, (started - prev_ts.astimezone(timezone.utc)).total_seconds() / 3600.0
        )
    else:
        elapsed_h = max(
            1e-9, (datetime.now(timezone.utc) - started).total_seconds() / 3600.0
        )
    label_velocity = label_count_delta / elapsed_h

    promoted = should_retrain and (map_delta > 0.01)
    if promoted and best_checkpoint.exists():
        active_ckpt = Path(__file__).resolve().parents[1] / "detection" / "checkpoints" / "active.pt"
        _promote_model(best_checkpoint, active_ckpt)

    iteration_number = (previous.iteration + 1) if previous else 1
    row = IterationRecord(
        iteration=iteration_number,
        timestamp=datetime.now(timezone.utc).isoformat(),
        label_count=label_count,
        map50=new_map50,
        promoted=promoted,
    )
    iterations.append(row)
    _write_iterations(iterations_path, iterations)

    run = wandb.init(
        project=os.getenv("WANDB_PROJECT", "darkwater"),
        entity=os.getenv("WANDB_ENTITY"),
        tags=["darkwater", "sar", "active-learning"],
        name=f"al-iteration-{iteration_number}",
        reinit=True,
        config={
            "iteration": iteration_number,
            "project_id": project_id,
            "dataset_yaml": str(dataset_yaml),
        },
    )
    wandb.log(
        {
            "active_learning/iteration": iteration_number,
            "active_learning/pulled_labels": pulled_count,
            "active_learning/merged_labels": merged_count,
            "active_learning/retrain_gate_min_labels": min_new_labels_to_retrain,
            "active_learning/retrained": int(should_retrain),
            "active_learning/label_count": label_count,
            "active_learning/label_count_delta": label_count_delta,
            "active_learning/map50": new_map50,
            "active_learning/map50_delta": map_delta,
            "active_learning/label_velocity_per_hour": label_velocity,
            "active_learning/promoted": int(promoted),
        }
    )
    wandb.save(str(iterations_path))
    run.finish()

    logger.info(
        "AL iteration=%s pulled=%s merged=%s label_count=%s map50=%.4f delta=%.4f promoted=%s",
        iteration_number,
        pulled_count,
        merged_count,
        label_count,
        new_map50,
        map_delta,
        promoted,
    )
    return row


@app.command("run")
def run_cli(
    project_id: int = typer.Option(..., "--project-id"),
    dataset_yaml: Path = typer.Option(..., "--dataset-yaml"),
    queue_db_path: Path = typer.Option(
        Path(os.getenv("LABELING_QUEUE_DB", "/app/data/labeling_queue.sqlite")),
        "--queue-db-path",
    ),
    corrected_labels_dir: Path = typer.Option(
        Path(__file__).resolve().parent / "corrected_labels",
        "--corrected-labels-dir",
    ),
    iterations_path: Path = typer.Option(
        Path(__file__).resolve().parent / "iterations.json",
        "--iterations-path",
    ),
    min_new_labels_to_retrain: int = typer.Option(
        int(os.getenv("MIN_NEW_LABELS_TO_RETRAIN", "100")),
        "--min-new-labels-to-retrain",
        help="Retraining starts only when pulled labels >= this threshold.",
    ),
    freeze_backbone: bool = typer.Option(
        True,
        "--freeze-backbone/--no-freeze-backbone",
        help="Freeze early YOLO layers and fine-tune detection heads.",
    ),
    freeze_layers: int = typer.Option(
        int(os.getenv("TRAIN_FREEZE_LAYERS", "10")),
        "--freeze-layers",
        help="Number of early YOLO layers to freeze when freeze-backbone is enabled.",
    ),
) -> None:
    row = retrain_iteration(
        project_id=project_id,
        dataset_yaml=dataset_yaml,
        queue_db_path=queue_db_path,
        corrected_labels_dir=corrected_labels_dir,
        iterations_path=iterations_path,
        min_new_labels_to_retrain=min_new_labels_to_retrain,
        freeze_backbone=freeze_backbone,
        freeze_layers=freeze_layers,
    )
    typer.echo(row.model_dump_json(indent=2))


if __name__ == "__main__":
    app()
