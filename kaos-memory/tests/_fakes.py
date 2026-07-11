"""Deterministic, offline test doubles shared across store tests."""

import hashlib

from mem0.embeddings.base import EmbeddingBase

DIM = 64


class DeterministicEmbedder(EmbeddingBase):
    """Hash bag-of-words -> fixed-dim L2-normalised vector.

    Identical text yields an identical vector, so cross-owner facts can be made
    exact nearest neighbours to prove the vector store pre-filters by owner rather
    than post-filtering a global top-k. No network or API key required.
    """

    def __init__(self, config=None):
        self.config = config

    def embed(self, text, memory_action=None):
        vec = [0.0] * DIM
        for tok in str(text).lower().split():
            h = int(hashlib.md5(tok.encode()).hexdigest(), 16)
            vec[h % DIM] += 1.0
        norm = sum(v * v for v in vec) ** 0.5 or 1.0
        return [v / norm for v in vec]
