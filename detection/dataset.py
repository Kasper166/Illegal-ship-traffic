from __future__ import annotations

import argparse
from collections import defaultdict
from pathlib import Path

import pandas as pd
from PIL import Image

from shared.logging import get_logger

logger = get_logger("detection.dataset")

CLASS_MAP = {
    "fishing": 0,
    "non-fishing": 1,
}
DISCARD_CLASS = "infrastructure"


def _pick_column(df: pd.DataFrame, candidates: list[str]) -> str:
    for c in candidates:
        if c in df.columns:
            return c
    raise ValueError(f"Missing one of required columns: {candidates}")


def _normalize_class(value: str) -> str:
    return str(value).strip().lower()


def _to_yolo_bbox(x: float, y: float, w: float, h: float, img_w: int, img_h: int) -> tuple[float, float, float, float]:
    x_center = (x + (w / 2.0)) / float(img_w)
    y_center = (y + (h / 2.0)) / float(img_h)
    width = w / float(img_w)
    height = h / float(img_h)
    return x_center, y_center, width, height


def convert_xview3_csv_to_yolo(
    annotations_csv: Path,
    images_dir: Path,
    labels_out_dir: Path,
) -> dict[str, int]:
    df = pd.read_csv(annotations_csv)
    labels_out_dir.mkdir(parents=True, exist_ok=True)

    image_col = _pick_column(df, ["image_id", "image", "image_name", "file_name", "filename"])
    class_col = _pick_column(df, ["class", "label", "vessel_type"])
    x_col = _pick_column(df, ["x", "xmin", "left"])
    y_col = _pick_column(df, ["y", "ymin", "top"])
    w_col = _pick_column(df, ["width", "w", "bbox_width"])
    h_col = _pick_column(df, ["height", "h", "bbox_height"])

    rows_by_image: dict[str, list[pd.Series]] = defaultdict(list)
    kept = 0
    discarded = 0

    for _, row in df.iterrows():
        cls = _normalize_class(str(row[class_col]))
        if cls == DISCARD_CLASS:
            discarded += 1
            continue
        if cls not in CLASS_MAP:
            discarded += 1
            continue
        image_name = str(row[image_col])
        rows_by_image[image_name].append(row)
        kept += 1

    images_processed = 0
    for image_name, rows in rows_by_image.items():
        image_path = images_dir / image_name
        if not image_path.exists():
            # Support CSV IDs without extension.
            matches = list(images_dir.glob(f"{image_name}.*"))
            if not matches:
                raise FileNotFoundError(f"Image not found for annotation: {image_name}")
            image_path = matches[0]

        with Image.open(image_path) as img:
            img_w, img_h = img.size

        label_path = labels_out_dir / f"{image_path.stem}.txt"
        lines: list[str] = []
        for row in rows:
            cls = _normalize_class(str(row[class_col]))
            class_id = CLASS_MAP[cls]
            x = float(row[x_col])
            y = float(row[y_col])
            w = float(row[w_col])
            h = float(row[h_col])

            if w <= 0 or h <= 0:
                raise AssertionError(f"Invalid non-positive bbox size in image {image_name}: {(x, y, w, h)}")
            if x < 0 or y < 0 or (x + w) > img_w or (y + h) > img_h:
                raise AssertionError(
                    f"Annotation out of bounds for image {image_name}: "
                    f"bbox={(x, y, w, h)} image_size={(img_w, img_h)}"
                )

            xc, yc, wn, hn = _to_yolo_bbox(x, y, w, h, img_w, img_h)
            lines.append(f"{class_id} {xc:.6f} {yc:.6f} {wn:.6f} {hn:.6f}")

        label_path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
        images_processed += 1

    logger.info(
        "xView3 conversion complete: images=%s kept_annotations=%s discarded=%s labels_dir=%s",
        images_processed,
        kept,
        discarded,
        labels_out_dir,
    )
    return {
        "images_processed": images_processed,
        "kept_annotations": kept,
        "discarded_annotations": discarded,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Convert xView3 CSV annotations to YOLO format.")
    parser.add_argument("annotations_csv", type=Path, help="Path to xView3 annotations CSV.")
    parser.add_argument("images_dir", type=Path, help="Directory containing patch images.")
    parser.add_argument("labels_out_dir", type=Path, help="Output directory for YOLO label .txt files.")
    args = parser.parse_args()
    convert_xview3_csv_to_yolo(
        annotations_csv=args.annotations_csv,
        images_dir=args.images_dir,
        labels_out_dir=args.labels_out_dir,
    )


if __name__ == "__main__":
    main()
