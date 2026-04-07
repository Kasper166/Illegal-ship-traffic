from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

import wandb
from ultralytics import YOLO

from shared.logging import get_logger

logger = get_logger("detection.train")


def _extract_metric(metrics: dict[str, Any], keys: list[str]) -> float:
    for key in keys:
        if key in metrics:
            value = metrics[key]
            if isinstance(value, (int, float)):
                return float(value)
    return 0.0


def train(
    dataset_yaml: Path,
    *,
    freeze_backbone: bool = False,
    freeze_layers: int = 10,
) -> Path:
    model_name = os.getenv("YOLO_MODEL_BASE", "yolov8m.pt")
    epochs = int(os.getenv("TRAIN_EPOCHS", "100"))
    batch_size = int(os.getenv("TRAIN_BATCH_SIZE", "16"))
    imgsz = int(os.getenv("TRAIN_IMG_SIZE", "640"))
    device = os.getenv("TRAIN_DEVICE", "cpu")
    project_name = os.getenv("WANDB_PROJECT", "darkwater")
    run_name = os.getenv("WANDB_RUN_NAME", f"baseline-{dataset_yaml.stem}")

    checkpoints_dir = Path(__file__).resolve().parent / "checkpoints"
    checkpoints_dir.mkdir(parents=True, exist_ok=True)

    run = wandb.init(
        project=project_name,
        entity=os.getenv("WANDB_ENTITY"),
        tags=["darkwater", "sar", "baseline"],
        config={
            "model": model_name,
            "dataset_yaml": str(dataset_yaml),
            "epochs": epochs,
            "batch_size": batch_size,
            "imgsz": imgsz,
            "device": device,
            "freeze_backbone": freeze_backbone,
            "freeze_layers": freeze_layers,
        },
        name=run_name,
        reinit=True,
    )

    logger.info("Starting YOLOv8 fine-tuning with model=%s data=%s", model_name, dataset_yaml)
    model = YOLO(model_name)
    results = model.train(
        data=str(dataset_yaml),
        epochs=epochs,
        batch=batch_size,
        imgsz=imgsz,
        device=device,
        project=str(checkpoints_dir),
        name=run_name,
        exist_ok=True,
        pretrained=True,
        freeze=freeze_layers if freeze_backbone else 0,
        verbose=True,
    )

    metrics = dict(getattr(results, "results_dict", {}) or {})
    precision = _extract_metric(metrics, ["metrics/precision(B)", "metrics/precision"])
    recall = _extract_metric(metrics, ["metrics/recall(B)", "metrics/recall"])
    map50 = _extract_metric(metrics, ["metrics/mAP50(B)", "metrics/mAP50"])

    save_dir = Path(getattr(results, "save_dir", checkpoints_dir / run_name))
    best_ckpt = save_dir / "weights" / "best.pt"
    if not best_ckpt.exists():
        # Fallback for runs that only produce last.pt.
        best_ckpt = save_dir / "weights" / "last.pt"

    final_ckpt = checkpoints_dir / f"{run_name}-best.pt"
    if best_ckpt.exists():
        final_ckpt.write_bytes(best_ckpt.read_bytes())
    else:
        logger.warning("No checkpoint found in %s", save_dir / "weights")

    report = {
        "run_name": run_name,
        "dataset_yaml": str(dataset_yaml),
        "best_checkpoint": str(final_ckpt),
        "precision": precision,
        "recall": recall,
        "map50": map50,
    }
    report_path = checkpoints_dir / "training_report.json"
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    wandb.log(
        {
            "final/precision": precision,
            "final/recall": recall,
            "final/map50": map50,
            "artifacts/best_checkpoint": str(final_ckpt),
        }
    )
    if final_ckpt.exists():
        wandb.save(str(final_ckpt))
    wandb.save(str(report_path))
    run.finish()

    logger.info(
        "Training complete. precision=%.4f recall=%.4f mAP50=%.4f report=%s",
        precision,
        recall,
        map50,
        report_path,
    )
    return report_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Fine-tune YOLOv8m on xView3-SAR.")
    parser.add_argument(
        "dataset_yaml",
        type=Path,
        help="Path to dataset YAML config file.",
    )
    args = parser.parse_args()
    train(args.dataset_yaml)


if __name__ == "__main__":
    main()
