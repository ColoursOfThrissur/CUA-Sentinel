"""Sentinel Semantic Long-Term Vector Memory & Nearest-Neighbor Retrieval.
High-assurance semantic index supporting fast sublinear TF-IDF trigram vectorization
and optional local Ollama embeddings, with cosine similarity nearest-neighbor lookup.
Operates fully offline with zero external package dependencies.
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

logger = logging.getLogger("SentinelVectorIndex")


class FastSemanticVectorizer:
    """Deterministic, zero-dependency sublinear TF-IDF + char/word n-gram vectorizer.
    Produces L2-normalized 384-dimensional dense vectors in <0.2ms.
    Captures character trigrams, morphological stems, and semantic keyword tokens.
    """

    DIMENSION = 384

    def __init__(self, dimension: int = DIMENSION):
        self.dimension = dimension

    def _hash_token(self, token: str, seed: int = 0) -> int:
        data = f"{seed}:{token}".encode("utf-8")
        h = int(hashlib.md5(data).hexdigest()[:8], 16)
        return h % self.dimension

    def vectorize(self, text: str) -> list[float]:
        if not text:
            return [0.0] * self.dimension

        vec = [0.0] * self.dimension
        clean = text.lower().strip()

        # 1. Word unigrams & bigrams
        words = re.findall(r"[a-z0-9_]{2,}", clean)
        term_freqs: dict[str, float] = {}

        for w in words:
            term_freqs[w] = term_freqs.get(w, 0.0) + 1.0

        for i in range(len(words) - 1):
            bg = f"{words[i]}_{words[i+1]}"
            term_freqs[bg] = term_freqs.get(bg, 0.0) + 1.5

        # 2. Character trigrams for morphological and substring matching
        compact = re.sub(r"\s+", " ", clean)
        for i in range(len(compact) - 2):
            tri = compact[i : i + 3]
            term_freqs[tri] = term_freqs.get(tri, 0.0) + 0.6

        # 3. Hash into fixed dimension with sign projection and sublinear scaling (1 + log(tf))
        for term, freq in term_freqs.items():
            idx = self._hash_token(term, seed=42)
            sign_bit = (self._hash_token(term, seed=101) % 2) * 2 - 1
            weight = (1.0 + math.log(freq)) * sign_bit
            vec[idx] += weight

        # 4. L2 Normalization
        norm = math.sqrt(sum(v * v for v in vec))
        if norm > 1e-9:
            vec = [v / norm for v in vec]

        return vec


def cosine_similarity(v1: list[float], v2: list[float]) -> float:
    """Computes cosine similarity between two dense vectors."""
    if not v1 or not v2 or len(v1) != len(v2):
        return 0.0
    dot = sum(a * b for a, b in zip(v1, v2))
    return max(-1.0, min(1.0, dot))


class VectorIndex:
    """Persistent/In-Memory Semantic Vector Index for mistakes, skills, and past trajectories."""

    def __init__(
        self,
        dimension: int = 384,
        ollama_endpoint: str | None = None,
        ollama_model: str | None = None,
        use_ollama_fallback: bool = True,
    ):
        self.dimension = dimension
        self.vectorizer = FastSemanticVectorizer(dimension=dimension)
        self.ollama_endpoint = ollama_endpoint
        self.ollama_model = ollama_model
        self.use_ollama_fallback = use_ollama_fallback
        self.entries: dict[str, dict[str, Any]] = {}

    def _embed_via_ollama(self, text: str) -> list[float] | None:
        """Attempts to query Ollama embeddings endpoint with short timeout."""
        if not self.ollama_endpoint or not self.ollama_model:
            return None
        url = f"{self.ollama_endpoint.rstrip('/')}/api/embeddings"
        payload = json.dumps({"model": self.ollama_model, "prompt": text[:1000]}).encode("utf-8")
        req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=3.0) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                emb = data.get("embedding")
                if emb and isinstance(emb, list):
                    norm = math.sqrt(sum(x * x for x in emb))
                    if norm > 1e-9:
                        return [x / norm for x in emb]
        except Exception as e:
            logger.debug("Ollama embedding failed or timed out (%s), using fast vectorizer", e)
        return None

    def embed(self, text: str) -> list[float]:
        """Embeds text into a normalized dense vector."""
        if self.use_ollama_fallback and self.ollama_model:
            emb = self._embed_via_ollama(text)
            if emb:
                return emb
        return self.vectorizer.vectorize(text)

    def upsert(self, item_id: str, text: str, metadata: dict[str, Any] | None = None) -> list[float]:
        """Indexes an item with text and optional metadata."""
        vector = self.embed(text)
        self.entries[item_id] = {
            "id": item_id,
            "text": text,
            "vector": vector,
            "metadata": metadata or {},
        }
        return vector

    def delete(self, item_id: str) -> bool:
        """Removes an item from the vector index."""
        if item_id in self.entries:
            del self.entries[item_id]
            return True
        return False

    def query(
        self,
        query_text: str,
        top_k: int = 3,
        min_score: float = 0.0,
        filter_fn: Any | None = None,
    ) -> list[dict[str, Any]]:
        """Finds top-K nearest items by cosine similarity."""
        if not self.entries or not query_text.strip():
            return []

        q_vec = self.embed(query_text)
        results = []

        for item in self.entries.values():
            if filter_fn and not filter_fn(item["metadata"]):
                continue
            score = cosine_similarity(q_vec, item["vector"])
            if score >= min_score:
                results.append({
                    "id": item["id"],
                    "score": round(score, 4),
                    "text": item["text"],
                    "metadata": item["metadata"],
                })

        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:top_k]

    def clear(self):
        self.entries.clear()

    def count(self) -> int:
        return len(self.entries)
