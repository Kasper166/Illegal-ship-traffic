from __future__ import annotations

import asyncio
import hashlib
import json
import os
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from pydantic import BaseModel
from redis.asyncio import Redis

from shared.logging import get_logger

logger = get_logger("ais.gfw_client")


class AISRecord(BaseModel):
    mmsi: str
    vessel_name: str | None = None
    flag: str | None = None
    vessel_type: str | None = None
    speed: float | None = None
    heading: float | None = None
    latitude: float | None = None
    longitude: float | None = None
    timestamp: datetime


class GFWClient:
    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        redis_url: str | None = None,
        timeout_s: float = 30.0,
        max_retries: int = 5,
    ) -> None:
        self.api_key = api_key or os.getenv("GLOBAL_FISHING_WATCH_API_KEY")
        if not self.api_key:
            raise ValueError("GLOBAL_FISHING_WATCH_API_KEY is required.")
        self.base_url = (
            base_url
            or os.getenv("GLOBAL_FISHING_WATCH_API_URL", "https://gateway.api.globalfishingwatch.org")
        ).rstrip("/")
        self.redis_url = redis_url or os.getenv("REDIS_URL", "redis://localhost:6379/0")
        self.timeout_s = timeout_s
        self.max_retries = max_retries

    def _cache_key(
        self,
        lat: float,
        lon: float,
        timestamp: datetime,
        radius_m: int,
        time_window_hours: int,
    ) -> str:
        rounded = f"{lat:.5f}|{lon:.5f}|{timestamp.astimezone(timezone.utc).isoformat()}|{radius_m}|{time_window_hours}"
        digest = hashlib.sha256(rounded.encode("utf-8")).hexdigest()
        return f"darkwater:gfw:ais:{digest}"

    async def _request_with_backoff(
        self,
        client: httpx.AsyncClient,
        *,
        endpoint: str,
        params: dict[str, Any],
    ) -> httpx.Response:
        backoff = 1.0
        for attempt in range(1, self.max_retries + 1):
            resp = await client.get(endpoint, params=params)
            if resp.status_code != 429:
                resp.raise_for_status()
                return resp
            if attempt == self.max_retries:
                resp.raise_for_status()
            await asyncio.sleep(backoff)
            backoff *= 2.0
        raise RuntimeError("Unexpected retry flow termination.")

    async def query_nearby_vessels(
        self,
        *,
        lat: float,
        lon: float,
        timestamp: datetime,
        radius_m: int = 500,
        time_window_hours: int = 2,
    ) -> list[AISRecord]:
        ts_utc = timestamp.astimezone(timezone.utc)
        cache_key = self._cache_key(lat, lon, ts_utc, radius_m, time_window_hours)
        redis = Redis.from_url(self.redis_url, decode_responses=True)

        cached = await redis.get(cache_key)
        if cached:
            data = json.loads(cached)
            records = [AISRecord.model_validate(item) for item in data]
            await redis.aclose()
            return records

        start_time = ts_utc - timedelta(hours=time_window_hours)
        end_time = ts_utc + timedelta(hours=time_window_hours)
        params = {
            "latitude": lat,
            "longitude": lon,
            "radius_m": radius_m,
            "start": start_time.isoformat(),
            "end": end_time.isoformat(),
        }
        endpoint = f"{self.base_url}/v3/ais/vessels/positions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/json",
        }

        async with httpx.AsyncClient(headers=headers, timeout=self.timeout_s) as client:
            resp = await self._request_with_backoff(client, endpoint=endpoint, params=params)
        payload = resp.json()
        items = payload.get("data") or payload.get("entries") or payload.get("results") or []

        records: list[AISRecord] = []
        for item in items:
            ts = (
                item.get("timestamp")
                or item.get("last_seen")
                or item.get("position_timestamp")
                or ts_utc.isoformat()
            )
            records.append(
                AISRecord(
                    mmsi=str(item.get("mmsi", "")),
                    vessel_name=item.get("vessel_name") or item.get("shipname"),
                    flag=item.get("flag"),
                    vessel_type=item.get("vessel_type") or item.get("shiptype"),
                    speed=float(item["speed"]) if item.get("speed") is not None else None,
                    heading=float(item["heading"]) if item.get("heading") is not None else None,
                    latitude=float(item["lat"]) if item.get("lat") is not None else (
                        float(item["latitude"]) if item.get("latitude") is not None else None
                    ),
                    longitude=float(item["lon"]) if item.get("lon") is not None else (
                        float(item["longitude"]) if item.get("longitude") is not None else None
                    ),
                    timestamp=datetime.fromisoformat(str(ts).replace("Z", "+00:00")),
                )
            )

        await redis.set(cache_key, json.dumps([r.model_dump(mode="json") for r in records]), ex=3600)
        await redis.aclose()
        logger.info(
            "GFW query lat=%.5f lon=%.5f radius=%sm window=±%sh returned=%s",
            lat,
            lon,
            radius_m,
            time_window_hours,
            len(records),
        )
        return records
