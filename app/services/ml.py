from __future__ import annotations

import hashlib
import logging
import math
import re
from collections import OrderedDict
from dataclasses import replace
from typing import Iterable

import numpy as np

from app.domain import RetrievalHit

logger = logging.getLogger(__name__)

TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_./:-]+|[\u4e00-\u9fff]")


def tokenize(text: str) -> list[str]:
    return TOKEN_PATTERN.findall(text.lower())


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    denom = np.linalg.norm(a) * np.linalg.norm(b)
    if denom == 0:
        return 0.0
    return float(np.dot(a, b) / denom)


class LruCache:
    def __init__(self, max_size: int) -> None:
        self.max_size = max(1, max_size)
        self._items: OrderedDict[str, object] = OrderedDict()

    def get(self, key: str) -> object | None:
        value = self._items.get(key)
        if value is None:
            return None
        self._items.move_to_end(key)
        return value

    def set(self, key: str, value: object) -> None:
        self._items[key] = value
        self._items.move_to_end(key)
        while len(self._items) > self.max_size:
            self._items.popitem(last=False)


class HashEmbeddingBackend:
    def __init__(self, dim: int = 384) -> None:
        self.dim = dim

    def _vectorize(self, text: str) -> list[float]:
        vector = np.zeros(self.dim, dtype=np.float32)
        for token in tokenize(text):
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "big") % self.dim
            vector[index] += 1.0
        norm = np.linalg.norm(vector)
        if norm > 0:
            vector = vector / norm
        return vector.astype(np.float32).tolist()

    def encode(self, texts: Iterable[str]) -> list[list[float]]:
        return [self._vectorize(text) for text in texts]


class EmbeddingService:
    def __init__(self, model_name: str, use_stub: bool = False, query_cache_size: int = 256) -> None:
        self.model_name = model_name
        self.use_stub = use_stub
        self._backend = None
        self._query_cache = LruCache(query_cache_size)

    def _load_backend(self):
        if self._backend is not None:
            return self._backend
        if self.use_stub:
            self._backend = HashEmbeddingBackend()
            return self._backend
        try:
            from FlagEmbedding import BGEM3FlagModel
        except Exception as exc:  # pragma: no cover - optional dependency
            logger.warning("FlagEmbedding unavailable, falling back to hash embeddings: %s", exc)
            self._backend = HashEmbeddingBackend()
            return self._backend

        try:
            self._backend = BGEM3FlagModel(self.model_name, use_fp16=False)
        except Exception as exc:  # pragma: no cover - model download/runtime dependent
            logger.warning("Failed to load %s, falling back to hash embeddings: %s", self.model_name, exc)
            self._backend = HashEmbeddingBackend()
        return self._backend

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        backend = self._load_backend()
        if isinstance(backend, HashEmbeddingBackend):
            return backend.encode(texts)
        result = backend.encode(texts, batch_size=min(8, max(1, len(texts))), max_length=2048)
        return result["dense_vecs"].tolist()

    def embed_query(self, text: str) -> list[float]:
        cache_key = normalize_cache_key(text)
        cached = self._query_cache.get(cache_key)
        if cached is not None:
            return list(cached)
        vector = self.embed_documents([text])[0]
        self._query_cache.set(cache_key, tuple(vector))
        return vector


class RerankerService:
    def __init__(self, model_name: str, use_stub: bool = False, score_cache_size: int = 4096) -> None:
        self.model_name = model_name
        self.use_stub = use_stub
        self._backend = None
        self._score_cache = LruCache(score_cache_size)

    def _load_backend(self):
        if self._backend is not None:
            return self._backend
        if self.use_stub:
            self._backend = "stub"
            return self._backend
        try:
            from FlagEmbedding import FlagReranker
        except Exception as exc:  # pragma: no cover - optional dependency
            logger.warning("FlagReranker unavailable, falling back to lexical reranking: %s", exc)
            self._backend = "stub"
            return self._backend

        try:
            self._backend = FlagReranker(self.model_name, use_fp16=False)
        except Exception as exc:  # pragma: no cover - model download/runtime dependent
            logger.warning("Failed to load %s, falling back to lexical reranking: %s", self.model_name, exc)
            self._backend = "stub"
        return self._backend

    def _lexical_score(self, query: str, text: str) -> float:
        query_tokens = tokenize(query)
        text_tokens = tokenize(text)
        if not query_tokens or not text_tokens:
            return 0.0
        overlap = sum(1 for token in query_tokens if token in text_tokens)
        density = overlap / max(len(query_tokens), 1)
        coverage = overlap / math.sqrt(max(len(text_tokens), 1))
        return float(density + coverage)

    def _score_cache_key(self, query: str, text: str) -> str:
        return f"{normalize_cache_key(query)}::{normalize_cache_key(text)}"

    def rerank(self, query: str, hits: list[RetrievalHit]) -> list[RetrievalHit]:
        if not hits:
            return []
        backend = self._load_backend()
        cached_scores: list[float | None] = []
        misses: list[tuple[int, RetrievalHit]] = []
        for index, hit in enumerate(hits):
            cached = self._score_cache.get(self._score_cache_key(query, hit.plain_text))
            cached_scores.append(float(cached) if cached is not None else None)
            if cached is None:
                misses.append((index, hit))

        if misses:
            if backend == "stub":
                miss_scores = [self._lexical_score(query, hit.plain_text) + hit.fusion_score for _, hit in misses]
            else:
                pairs = [(query, hit.plain_text) for _, hit in misses]
                try:
                    miss_scores = [float(score) for score in backend.compute_score(pairs, batch_size=min(8, len(pairs)))]
                except Exception as exc:  # pragma: no cover - runtime/model dependent
                    logger.warning("Reranker runtime failed, falling back to lexical reranking: %s", exc)
                    self._backend = "stub"
                    backend = "stub"
                    miss_scores = [self._lexical_score(query, hit.plain_text) + hit.fusion_score for _, hit in misses]
            for (index, hit), score in zip(misses, miss_scores):
                cache_key = self._score_cache_key(query, hit.plain_text)
                self._score_cache.set(cache_key, float(score))
                cached_scores[index] = float(score)

        reranked = [
            replace(hit, rerank_score=float(cached_scores[index] or 0.0))
            for index, hit in enumerate(hits)
        ]
        return sorted(reranked, key=lambda item: item.rerank_score, reverse=True)


def normalize_cache_key(text: str, limit: int = 1200) -> str:
    normalized = " ".join(text.lower().split())
    if len(normalized) <= limit:
        return normalized
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    return f"{normalized[:limit]}#{digest[:12]}"
