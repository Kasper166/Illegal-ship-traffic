from __future__ import annotations

import math
from datetime import datetime, timezone

from pydantic import BaseModel

from ais.gfw_client import AISRecord
from detection.inference import Detection


class DarkVesselAlert(BaseModel):
    detection: Detection
    dark_vessel: bool
    confidence_dark: float
    supporting_ais_records: list[AISRecord]
    evaluated_at: datetime


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371000.0
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2.0) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2.0) ** 2
    return 2.0 * r * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))


def _record_lat_lon(record: AISRecord) -> tuple[float, float] | None:
    # GFW response shape can vary by endpoint; only score distance when position exists.
    lat = getattr(record, "latitude", None)
    lon = getattr(record, "longitude", None)
    if lat is None or lon is None:
        return None
    return float(lat), float(lon)


def assess_dark_vessel(
    detection: Detection,
    ais_records: list[AISRecord],
    *,
    tolerance_m: int = 500,
) -> DarkVesselAlert:
    det_lat, det_lon = detection.lat_lon_center
    if not ais_records:
        return DarkVesselAlert(
            detection=detection,
            dark_vessel=True,
            confidence_dark=1.0,
            supporting_ais_records=[],
            evaluated_at=datetime.now(timezone.utc),
        )

    # Distance-weighted attenuation of dark score where close AIS exists.
    weights: list[float] = []
    for rec in ais_records:
        maybe_ll = _record_lat_lon(rec)
        if maybe_ll is None:
            continue
        rec_lat, rec_lon = maybe_ll
        d = _haversine_m(det_lat, det_lon, rec_lat, rec_lon)
        if d <= tolerance_m:
            weights.append(1.0 - (d / max(1.0, float(tolerance_m))))

    if not weights:
        # AIS records exist but none close enough to explain detection.
        confidence_dark = 0.9
        dark = True
    else:
        # Higher nearby AIS support -> lower dark confidence.
        support = max(weights)
        confidence_dark = max(0.0, min(1.0, 1.0 - support))
        dark = confidence_dark >= 0.5

    return DarkVesselAlert(
        detection=detection,
        dark_vessel=dark,
        confidence_dark=confidence_dark,
        supporting_ais_records=ais_records,
        evaluated_at=datetime.now(timezone.utc),
    )
