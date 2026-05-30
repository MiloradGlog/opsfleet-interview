"""The "Golden Bucket" — hybrid intelligence (brief R1).

Analyst-curated Trios (Question -> SQL -> Report) are embedded once and retrieved
by cosine similarity to steer SQL generation with few-shot examples. The embedder
is injected so the unit tests can run offline with a deterministic fake.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Callable, Protocol

import numpy as np

# An embedder turns a list of texts into a list of float vectors.
EmbedFn = Callable[[list[str]], list[list[float]]]


class Trio(dict):
    """A Golden Trio: {id, question, sql, report, tags?}. A dict subclass so it
    serializes trivially and reads naturally in prompts."""


class _Embeddings(Protocol):  # structural type for langchain embeddings objects
    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...
    def embed_query(self, text: str) -> list[float]: ...


def _cosine(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Cosine similarity of query vector ``a`` (d,) against matrix ``b`` (n, d)."""
    a_norm = a / (np.linalg.norm(a) + 1e-12)
    b_norm = b / (np.linalg.norm(b, axis=1, keepdims=True) + 1e-12)
    return b_norm @ a_norm


class GoldenBucket:
    """In-process vector index over seed Trios."""

    def __init__(self, trios: list[dict], embed_fn: EmbedFn, model_id: str,
                 cache_path: str | Path | None = None) -> None:
        self.trios: list[Trio] = [Trio(t) for t in trios]
        self._embed_fn = embed_fn
        self._model_id = model_id
        self._cache_path = Path(cache_path) if cache_path else None
        self._matrix: np.ndarray | None = None  # (n, d)

    # --- index lifecycle -----------------------------------------------------
    def ensure_index(self) -> None:
        """Embed all Trio questions (using the cache when valid)."""
        if self._matrix is not None:
            return
        vectors = self._load_cache()
        if vectors is None:
            questions = [t["question"] for t in self.trios]
            vectors = self._embed_fn(questions)
            self._save_cache(vectors)
        self._matrix = np.asarray(vectors, dtype=np.float32)

    def retrieve(self, question: str, k: int = 3) -> list[Trio]:
        """Return the top-``k`` most similar Trios to ``question``."""
        if not self.trios:
            return []
        self.ensure_index()
        q_vec = np.asarray(self._embed_fn([question])[0], dtype=np.float32)
        scores = _cosine(q_vec, self._matrix)  # type: ignore[arg-type]
        top = np.argsort(scores)[::-1][:k]
        return [self.trios[i] for i in top]

    # --- embedding cache (keyed on model id + question, so a model swap or an
    #     edited Trio forces a clean re-embed) --------------------------------
    def _cache_key(self) -> dict:
        return {"model": self._model_id, "questions": [t["question"] for t in self.trios]}

    def _load_cache(self) -> list[list[float]] | None:
        if not self._cache_path or not self._cache_path.exists():
            return None
        try:
            blob = json.loads(self._cache_path.read_text())
        except (json.JSONDecodeError, OSError):
            return None
        if blob.get("key") != self._cache_key():
            return None  # stale (model changed or Trios edited)
        return blob.get("vectors")

    def _save_cache(self, vectors: list[list[float]]) -> None:
        if not self._cache_path:
            return
        try:
            self._cache_path.write_text(json.dumps({"key": self._cache_key(), "vectors": vectors}))
        except OSError:
            pass  # cache is an optimization; never fatal


def load_trios(path: str | Path) -> list[dict]:
    return json.loads(Path(path).read_text())


def build_golden_bucket(settings, embeddings: _Embeddings) -> GoldenBucket:
    """Wire a GoldenBucket from settings + a langchain embeddings object."""
    trios = load_trios(settings.trios_path)

    def embed_fn(texts: list[str]) -> list[list[float]]:
        # embed_documents is the batched path; fine for both seed + single query.
        return embeddings.embed_documents(texts)

    return GoldenBucket(
        trios=trios,
        embed_fn=embed_fn,
        model_id=settings.embed_model,
        cache_path=settings.embeddings_cache_path,
    )
