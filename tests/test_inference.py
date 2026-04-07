from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from detection.inference import Detection, run_inference


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
        self.names = {0: "fishing", 1: "non-fishing"}

    def predict(
        self,
        source: list[str],
        conf: float,
        device: str,
        verbose: bool,
    ) -> list[FakeResult]:
        _ = (conf, device, verbose)
        out: list[FakeResult] = []
        for _img in source:
            # One low-confidence and one high-confidence detection per patch.
            out.append(
                FakeResult(
                    boxes=[
                        FakeBox([10.0, 20.0, 30.0, 40.0], conf=0.40, cls_idx=0),
                        FakeBox([50.0, 60.0, 90.0, 110.0], conf=0.80, cls_idx=1),
                    ],
                    orig_shape=(512, 512),
                )
            )
        return out


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


def _write_patch_with_geojson(base_dir: Path, name: str) -> None:
    (base_dir / f"{name}.png").write_bytes(b"not-a-real-image")
    geojson = {
        "type": "Feature",
        "properties": {},
        "geometry": {
            "type": "Polygon",
            "coordinates": [
                [
                    [1.0, 2.0],
                    [3.0, 2.0],
                    [3.0, 4.0],
                    [1.0, 4.0],
                    [1.0, 2.0],
                ]
            ],
        },
    }
    (base_dir / f"{name}.geojson").write_text(json.dumps(geojson), encoding="utf-8")


def test_run_inference_jsonl_schema_and_flagging(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("ACTIVE_LEARNING_THRESHOLD", "0.45")

    scene_dir = tmp_path / "scene_a"
    scene_dir.mkdir(parents=True, exist_ok=True)
    _write_patch_with_geojson(scene_dir, "patch_000001")
    _write_patch_with_geojson(scene_dir, "patch_000002")

    monkeypatch.setattr("detection.inference.YOLO", FakeYOLO)
    monkeypatch.setattr("detection.inference.wandb", FakeWandb())

    output_jsonl = tmp_path / "detections.jsonl"
    run_inference(
        patches_dir=tmp_path,
        model_path=tmp_path / "fake-model.pt",
        output_jsonl=output_jsonl,
        batch_size=2,
    )

    lines = output_jsonl.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 4  # 2 patches * 2 detections each

    parsed = [Detection.model_validate_json(line) for line in lines]
    assert all(det.scene_id == "scene_a" for det in parsed)
    assert all(det.tile_id.startswith("patch_") for det in parsed)
    assert all(len(det.pixel_coords) == 4 for det in parsed)
    assert all(len(det.bbox_xyxy) == 4 for det in parsed)

    low_conf = [det for det in parsed if det.confidence < 0.45]
    high_conf = [det for det in parsed if det.confidence >= 0.45]
    assert low_conf and all(det.flagged_for_review for det in low_conf)
    assert high_conf and all(not det.flagged_for_review for det in high_conf)
