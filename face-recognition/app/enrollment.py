"""Per-person embedding store — in-memory with JSON disk persistence."""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)

_MODELS_DIR = Path(os.getenv("INSIGHTFACE_HOME", "/root/.insightface")) / "embeddings"


class EnrollmentStore:
    """Manages enrolled face embeddings with memory + disk persistence."""

    def __init__(self, store_dir: Path | None = None) -> None:
        self._dir = Path(store_dir) if store_dir else _MODELS_DIR
        self.enrolled: dict[str, list[np.ndarray]] = {}

    def load_from_disk(self) -> None:
        """Load all persisted embeddings from JSON files on startup."""
        self._dir.mkdir(parents=True, exist_ok=True)
        for path in self._dir.glob("*.json"):
            name = path.stem
            try:
                data = json.loads(path.read_text())
                self.enrolled[name] = [np.array(e, dtype=np.float32) for e in data]
                logger.info("Loaded %d embeddings for %s", len(data), name)
            except Exception as exc:
                logger.warning("Failed to load embeddings for %s: %s", name, exc)

    def save_embedding(self, name: str, normed_embedding: np.ndarray) -> None:
        """Append embedding for name and persist to disk."""
        if name not in self.enrolled:
            self.enrolled[name] = []
        self.enrolled[name].append(normed_embedding)
        self._persist(name)

    def delete_person(self, name: str) -> int:
        """Remove all embeddings for name. Returns count removed."""
        count = len(self.enrolled.pop(name, []))
        path = self._dir / f"{name}.json"
        if path.exists():
            path.unlink()
        logger.info("Deleted %d embeddings for %s", count, name)
        return count

    def get_count(self, name: str) -> int:
        return len(self.enrolled.get(name, []))

    def list_persons(self) -> list[str]:
        return list(self.enrolled.keys())

    def _persist(self, name: str) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)
        path = self._dir / f"{name}.json"
        data = [e.tolist() for e in self.enrolled[name]]
        path.write_text(json.dumps(data))
