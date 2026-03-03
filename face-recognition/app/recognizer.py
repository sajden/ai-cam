"""InsightFace FaceAnalysis wrapper with cosine similarity matching."""
from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

_THRESHOLD = float(os.getenv("FACE_RECOGNITION_THRESHOLD", "0.55"))


class FaceRecognizer:
    """Wraps InsightFace buffalo_l model for face detection and embedding."""

    def __init__(self, enrollment_store) -> None:
        self._store = enrollment_store
        self._app = None

    def _load(self) -> None:
        """Lazy-load InsightFace model (heavy, do once on first use)."""
        if self._app is not None:
            return
        import insightface
        from insightface.app import FaceAnalysis

        providers = ["CUDAExecutionProvider", "CPUExecutionProvider"]
        app = FaceAnalysis(name="buffalo_l", providers=providers)
        app.prepare(ctx_id=0, det_size=(640, 640))
        active = app.models  # triggers GPU/CPU selection log
        try:
            import onnxruntime as ort
            used = ort.get_device()
            cuda_active = "CUDAExecutionProvider" in str(ort.get_available_providers())
            logger.info("CUDA provider active: %s", cuda_active)
        except Exception:
            pass
        self._app = app
        logger.info("InsightFace buffalo_l loaded")

    def _embed(self, jpeg_bytes: bytes) -> tuple[list, np.ndarray | None]:
        """Detect faces and return (faces, normed_embedding_of_largest_face)."""
        self._load()
        import cv2

        arr = np.frombuffer(jpeg_bytes, np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if img is None:
            return [], None
        faces = self._app.get(img)
        if not faces:
            return faces, None
        # Pick largest face by bounding box area
        face = max(faces, key=lambda f: (f.bbox[2] - f.bbox[0]) * (f.bbox[3] - f.bbox[1]))
        emb = face.normed_embedding
        return faces, emb

    def recognize(self, jpeg_bytes: bytes) -> dict:
        """
        Identify a person from JPEG bytes.

        Returns dict with: matched, name, confidence, bbox, face_detected.
        """
        faces, emb = self._embed(jpeg_bytes)
        if not faces:
            return {"matched": False, "name": None, "confidence": 0.0, "bbox": None, "face_detected": False}

        face = max(faces, key=lambda f: (f.bbox[2] - f.bbox[0]) * (f.bbox[3] - f.bbox[1]))
        bbox = [int(x) for x in face.bbox]

        if emb is None:
            return {"matched": False, "name": None, "confidence": 0.0, "bbox": bbox, "face_detected": True}

        best_name: str | None = None
        best_score: float = 0.0

        for name, embeddings in self._store.enrolled.items():
            for stored_emb in embeddings:
                score = float(np.dot(emb, stored_emb))
                if score > best_score:
                    best_score = score
                    best_name = name

        threshold = float(os.getenv("FACE_RECOGNITION_THRESHOLD", str(_THRESHOLD)))
        matched = best_score >= threshold
        return {
            "matched": matched,
            "name": best_name if matched else None,
            "confidence": round(best_score, 4),
            "bbox": bbox,
            "face_detected": True,
        }

    def enroll(self, name: str, jpeg_bytes: bytes) -> dict:
        """
        Extract embedding from JPEG and store under name.

        Returns dict with: ok, embedding_count, reason (if failed).
        """
        _, emb = self._embed(jpeg_bytes)
        if emb is None:
            return {"ok": False, "reason": "no_face_detected"}
        self._store.save_embedding(name, emb)
        count = self._store.get_count(name)
        logger.info("Enrolled %s (total embeddings: %d)", name, count)
        return {"ok": True, "name": name, "embedding_count": count}
