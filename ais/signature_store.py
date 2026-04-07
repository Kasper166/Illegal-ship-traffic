from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

import numpy as np
import timm
import torch
from qdrant_client import QdrantClient
from qdrant_client.http import models as qmodels


@dataclass(frozen=True)
class SimilarDetection:
    score: float
    payload: dict[str, Any]


class VesselSignatureStore:
    """Store and query SAR vessel signatures in Qdrant using cosine similarity."""

    COLLECTION_NAME = "vessel_signatures"

    def __init__(
        self,
        *,
        qdrant_url: str = "http://localhost:6333",
        qdrant_api_key: str | None = None,
        model_name: str | None = None,
        device: str | None = None,
    ) -> None:
        self.device = torch.device(
            device or ("cuda" if torch.cuda.is_available() else "cpu")
        )
        self.model_name = model_name or self._pick_backbone_name()
        self.model = self._build_feature_model(self.model_name, self.device)
        self.vector_size = self._infer_vector_size()

        self.client = QdrantClient(url=qdrant_url, api_key=qdrant_api_key)
        self._ensure_collection()

    @staticmethod
    def _pick_backbone_name() -> str:
        """Prefer DINOv2 when available, otherwise fall back to Swin Transformer."""
        preferred = [
            "vit_base_patch14_dinov2.lvd142m",
            "vit_small_patch14_dinov2.lvd142m",
            "swin_base_patch4_window7_224",
        ]
        available = set(timm.list_models(pretrained=True))
        for name in preferred:
            if name in available:
                return name
        # Final safe fallback.
        return "swin_tiny_patch4_window7_224"

    @staticmethod
    def _build_feature_model(model_name: str, device: torch.device) -> torch.nn.Module:
        """
        Create a timm backbone with classifier head removed for feature extraction.
        """
        model = timm.create_model(
            model_name,
            pretrained=True,
            num_classes=0,
            global_pool="avg",
        )
        model.eval()
        model.to(device)
        return model

    def _infer_vector_size(self) -> int:
        dummy = torch.zeros((1, 3, 224, 224), dtype=torch.float32, device=self.device)
        with torch.no_grad():
            feat = self.model(dummy)
        if feat.ndim != 2:
            raise RuntimeError(f"Unexpected embedding shape from backbone: {feat.shape}")
        return int(feat.shape[-1])

    def _ensure_collection(self) -> None:
        if self.client.collection_exists(self.COLLECTION_NAME):
            return
        self.client.create_collection(
            collection_name=self.COLLECTION_NAME,
            vectors_config=qmodels.VectorParams(
                size=self.vector_size,
                distance=qmodels.Distance.COSINE,
            ),
        )
        # Payload index speeds duplicate checks by detection_id.
        self.client.create_payload_index(
            collection_name=self.COLLECTION_NAME,
            field_name="detection_id",
            field_schema=qmodels.PayloadSchemaType.KEYWORD,
        )

    @staticmethod
    def _preprocess_patch(patch: np.ndarray) -> torch.Tensor:
        """
        Convert SAR patch ndarray to model-ready tensor [1, 3, 224, 224].
        """
        if patch.ndim != 2:
            raise ValueError("Expected a single-channel SAR patch with shape [H, W].")

        x = patch.astype(np.float32, copy=False)
        lo, hi = np.percentile(x, [2.0, 98.0])
        if hi <= lo:
            x = np.zeros_like(x, dtype=np.float32)
        else:
            x = np.clip(x, lo, hi)
            x = (x - lo) / (hi - lo)

        # Replicate single-channel SAR into 3 channels for timm backbones.
        x3 = np.stack([x, x, x], axis=0)  # [3, H, W]
        t = torch.from_numpy(x3).unsqueeze(0)  # [1, 3, H, W]
        t = torch.nn.functional.interpolate(
            t, size=(224, 224), mode="bilinear", align_corners=False
        )
        return t

    def _embed_patch(self, patch: np.ndarray) -> np.ndarray:
        """
        Generate fixed-length L2-normalized embedding for a SAR patch.
        """
        t = self._preprocess_patch(patch).to(self.device)
        with torch.no_grad():
            emb = self.model(t)  # [1, D]
        emb = emb.detach().cpu().numpy().reshape(-1).astype(np.float32)
        norm = float(np.linalg.norm(emb))
        if norm <= 0.0:
            raise RuntimeError("Model produced a zero-norm embedding.")
        emb = emb / norm
        return emb

    def _detection_exists(self, detection_id: str) -> bool:
        flt = qmodels.Filter(
            must=[
                qmodels.FieldCondition(
                    key="detection_id",
                    match=qmodels.MatchValue(value=detection_id),
                )
            ]
        )
        points, _ = self.client.scroll(
            collection_name=self.COLLECTION_NAME,
            scroll_filter=flt,
            limit=1,
            with_payload=False,
            with_vectors=False,
        )
        return len(points) > 0

    def upsert_detection(
        self,
        *,
        patch: np.ndarray,
        detection_id: str,
        scene_id: str,
        timestamp: datetime,
        lat: float,
        lon: float,
        is_dark_vessel: bool,
        vessel_class: str,
    ) -> bool:
        """
        Upsert a detection embedding with duplicate guard on detection_id.

        Returns:
            bool: True when inserted, False when duplicate was skipped.
        """
        if self._detection_exists(detection_id):
            return False

        vec = self._embed_patch(patch)
        ts = timestamp.astimezone(timezone.utc).isoformat()
        payload = {
            "detection_id": detection_id,
            "scene_id": scene_id,
            "timestamp": ts,
            "lat": float(lat),
            "lon": float(lon),
            "is_dark_vessel": bool(is_dark_vessel),
            "vessel_class": vessel_class,
        }
        point = qmodels.PointStruct(
            id=str(uuid4()),
            vector=vec.tolist(),
            payload=payload,
        )
        self.client.upsert(
            collection_name=self.COLLECTION_NAME,
            points=[point],
            wait=True,
        )
        return True

    def search_similar(self, patch: np.ndarray, top_k: int = 5) -> list[SimilarDetection]:
        """
        Search top-k similar detections for a SAR patch.
        """
        total = self.client.count(
            collection_name=self.COLLECTION_NAME,
            exact=False,
        ).count
        if total == 0:
            return []

        vec = self._embed_patch(patch)
        hits = self.client.search(
            collection_name=self.COLLECTION_NAME,
            query_vector=vec.tolist(),
            limit=max(1, int(top_k)),
            with_payload=True,
            with_vectors=False,
        )
        return [
            SimilarDetection(score=float(hit.score), payload=dict(hit.payload or {}))
            for hit in hits
        ]

    def is_anomalous(self, patch: np.ndarray, threshold: float = 0.7) -> bool:
        """
        Return True if nearest-neighbor cosine similarity is below threshold.
        Handles empty collections safely by returning True.
        """
        nearest = self.search_similar(patch, top_k=1)
        if not nearest:
            return True
        return nearest[0].score < float(threshold)
