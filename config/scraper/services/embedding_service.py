"""
Embedding service using sentence-transformers (100 % FREE).

Uses the ``paraphrase-multilingual-mpnet-base-v2`` model to generate
768-dimensional embedding vectors.  Supports 50+ languages including
Azerbaijani, English, and Russian — perfect for multilingual semantic search.

The service uses a **singleton pattern** so the model is loaded only once
across the entire Django/Celery process.

Usage:
    >>> from scraper.services.embedding_service import EmbeddingService
    >>> svc = EmbeddingService()
    >>> emb = svc.get_embedding("Şəki şəhərində yeni park açıldı")
    >>> len(emb)
    768
    >>> score = svc.calculate_similarity(emb, other_emb)
    >>> score > 0.65
    True
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np
from django.conf import settings

logger = logging.getLogger('scraper')

# Model name — multilingual, 768 dims, open-source
_MODEL_NAME: str = getattr(settings, 'EMBEDDING_MODEL', 'paraphrase-multilingual-mpnet-base-v2')
_EMBEDDING_DIM: int = getattr(settings, 'EMBEDDING_DIMENSION', 768)


class EmbeddingService:
    """
    Singleton service for generating multilingual text embeddings.

    The underlying ``SentenceTransformer`` model is loaded *once* and reused
    for all subsequent calls within the same process.

    Attributes:
        model: The loaded SentenceTransformer model instance.

    Example:
        >>> svc = EmbeddingService()
        >>> vec = svc.get_embedding("Bakı")
        >>> assert len(vec) == 768
    """

    _instance: EmbeddingService | None = None
    _model: Any = None  # SentenceTransformer instance

    def __new__(cls) -> EmbeddingService:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._load_model()
        return cls._instance

    # ------------------------------------------------------------------
    # Initialisation
    # ------------------------------------------------------------------

    def _load_model(self) -> None:
        """Load the sentence-transformers model (once per process)."""
        try:
            from sentence_transformers import SentenceTransformer

            logger.info("Loading embedding model: %s …", _MODEL_NAME)
            self._model = SentenceTransformer(_MODEL_NAME)
            logger.info("Embedding model loaded successfully (%d dims)", _EMBEDDING_DIM)
        except ImportError:
            logger.error(
                "sentence-transformers is not installed. "
                "Run: pip install sentence-transformers"
            )
            raise
        except Exception:
            logger.exception("Failed to load embedding model '%s'", _MODEL_NAME)
            raise

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_embedding(self, text: str) -> list[float]:
        """
        Generate a single embedding vector for the given text.

        Args:
            text: Input text (any language).

        Returns:
            A list of floats representing the embedding (dimension set by settings).

        Raises:
            ValueError: If text is empty or the model failed.
        """
        if not text or not text.strip():
            logger.warning("get_embedding called with empty text")
            return [0.0] * _EMBEDDING_DIM

        try:
            embedding = self._model.encode(text, show_progress_bar=False)
            result = embedding.tolist()

            # Validate dimensions
            if len(result) != _EMBEDDING_DIM:
                logger.error(
                    "Unexpected embedding dimension: got %d, expected %d",
                    len(result),
                    _EMBEDDING_DIM,
                )

            return result
        except Exception:
            logger.exception("Failed to generate embedding for text: '%s…'", text[:50])
            return [0.0] * _EMBEDDING_DIM

    def get_embeddings_batch(self, texts: list[str]) -> list[list[float]]:
        """
        Generate embeddings for multiple texts at once (faster than one-by-one).

        Args:
            texts: List of input texts.

        Returns:
            List of embedding vectors (same order as input).
        """
        if not texts:
            return []

        # Filter out empty strings but keep indices for re-assembly
        valid_indices: list[int] = []
        valid_texts: list[str] = []
        for idx, t in enumerate(texts):
            if t and t.strip():
                valid_indices.append(idx)
                valid_texts.append(t)

        if not valid_texts:
            return [[0.0] * _EMBEDDING_DIM for _ in texts]

        try:
            logger.info("Generating batch embeddings for %d texts …", len(valid_texts))
            embeddings = self._model.encode(valid_texts, show_progress_bar=False, batch_size=32)

            # Build result array with zeros for empty texts
            result: list[list[float]] = [[0.0] * _EMBEDDING_DIM for _ in texts]
            for i, idx in enumerate(valid_indices):
                result[idx] = embeddings[i].tolist()

            return result
        except Exception:
            logger.exception("Batch embedding failed for %d texts", len(texts))
            return [[0.0] * _EMBEDDING_DIM for _ in texts]

    @staticmethod
    def calculate_similarity(embedding1: list[float], embedding2: list[float]) -> float:
        """
        Calculate cosine similarity between two embedding vectors.

        Args:
            embedding1: First embedding vector.
            embedding2: Second embedding vector.

        Returns:
            A float between 0.0 (completely different) and 1.0 (identical).
            Values > 0.7 indicate a strong semantic match.
        """
        try:
            a = np.array(embedding1, dtype=np.float32)
            b = np.array(embedding2, dtype=np.float32)

            # Handle zero vectors
            norm_a = np.linalg.norm(a)
            norm_b = np.linalg.norm(b)
            if norm_a == 0 or norm_b == 0:
                return 0.0

            similarity = float(np.dot(a, b) / (norm_a * norm_b))
            # Clamp to [0, 1] (rounding errors can push slightly outside)
            return max(0.0, min(1.0, similarity))
        except Exception:
            logger.exception("Similarity calculation failed")
            return 0.0

    def find_similar_texts(
        self,
        query_embedding: list[float],
        corpus_embeddings: list[list[float]],
        threshold: float = 0.7,
        top_k: int = 10,
    ) -> list[dict[str, Any]]:
        """
        Find the most similar texts from a corpus of embeddings.

        Args:
            query_embedding: The query embedding vector.
            corpus_embeddings: List of corpus vectors.
            threshold: Minimum cosine similarity to include.
            top_k: Maximum number of results to return.

        Returns:
            A list of dicts ``{'index': int, 'score': float}`` sorted by
            descending similarity, filtered by *threshold*.
        """
        if not corpus_embeddings:
            return []

        try:
            query = np.array(query_embedding, dtype=np.float32)
            corpus = np.array(corpus_embeddings, dtype=np.float32)

            # Compute cosine similarities in bulk
            query_norm = np.linalg.norm(query)
            if query_norm == 0:
                return []

            corpus_norms = np.linalg.norm(corpus, axis=1)
            # Avoid division by zero
            corpus_norms[corpus_norms == 0] = 1e-10

            similarities = np.dot(corpus, query) / (corpus_norms * query_norm)

            # Filter by threshold and sort
            results: list[dict[str, Any]] = []
            for idx, score in enumerate(similarities):
                if score >= threshold:
                    results.append({'index': idx, 'score': float(score)})

            results.sort(key=lambda x: x['score'], reverse=True)
            return results[:top_k]

        except Exception:
            logger.exception("find_similar_texts failed")
            return []
