from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import Boolean, DateTime, Float, Integer, JSON, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class DetectionRecordORM(Base):
    __tablename__ = "detection_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    patch_id: Mapped[str] = mapped_column(String(255), index=True)
    tile_id: Mapped[str] = mapped_column(String(255), index=True)
    bbox_xyxy: Mapped[list[float]] = mapped_column(JSON)
    pixel_coords: Mapped[list[float]] = mapped_column(JSON)
    confidence: Mapped[float] = mapped_column(Float, index=True)
    class_label: Mapped[str] = mapped_column(String(128), index=True)
    lat: Mapped[float] = mapped_column(Float, index=True)
    lon: Mapped[float] = mapped_column(Float, index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    scene_id: Mapped[str] = mapped_column(String(255), index=True)
    flagged_for_review: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    is_dark: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class ModelMetricsORM(Base):
    __tablename__ = "model_metrics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    model_name: Mapped[str] = mapped_column(String(255), index=True)
    map50: Mapped[float] = mapped_column(Float, index=True)
    evaluated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class HealthResponse(BaseModel):
    status: str


class DetectionRecord(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int | None = None
    patch_id: str
    tile_id: str
    bbox_xyxy: list[float]
    pixel_coords: list[float]
    confidence: float
    class_label: str
    lat_lon_center: tuple[float, float]
    timestamp: datetime
    scene_id: str
    flagged_for_review: bool = False
    is_dark: bool = False

    @model_validator(mode="before")
    @classmethod
    def _coerce_lat_lon(cls, data: Any) -> Any:
        """Map separate lat/lon ORM columns into the lat_lon_center tuple field."""
        if isinstance(data, dict):
            if "lat_lon_center" not in data and "lat" in data and "lon" in data:
                data = {**data, "lat_lon_center": (data["lat"], data["lon"])}
            return data
        # ORM / attribute-bearing object without lat_lon_center attribute
        if hasattr(data, "lat") and hasattr(data, "lon") and not hasattr(data, "lat_lon_center"):
            return {
                "id": getattr(data, "id", None),
                "patch_id": data.patch_id,
                "tile_id": data.tile_id,
                "bbox_xyxy": list(data.bbox_xyxy),
                "pixel_coords": list(data.pixel_coords),
                "confidence": data.confidence,
                "class_label": data.class_label,
                "lat_lon_center": (data.lat, data.lon),
                "timestamp": data.timestamp,
                "scene_id": data.scene_id,
                "flagged_for_review": data.flagged_for_review,
                "is_dark": data.is_dark,
            }
        return data


class DetectionListResponse(BaseModel):
    total: int
    page: int
    page_size: int
    items: list[DetectionRecord]


class IterationRecord(BaseModel):
    iteration: int
    timestamp: str
    label_count: int
    map50: float
    promoted: bool


class StatsResponse(BaseModel):
    total_detections_today: int
    dark_vessel_count: int
    active_learning_iteration: int
    current_model_map: float


class ExportRequest(BaseModel):
    format: str = Field(pattern="^(csv|geojson)$")
