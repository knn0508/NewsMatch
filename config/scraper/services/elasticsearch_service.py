"""
ElasticSearch service for article indexing and vector search.

Manages a ``news_articles`` index with dense-vector fields for cosine
similarity search.  Articles are indexed with their embedding vectors
enabling semantic (vector) search alongside traditional text search.

Prerequisites:
    - ElasticSearch 8.x running (``docker run -d --name elasticsearch
      -p 9200:9200 -e "discovery.type=single-node"
      -e "xpack.security.enabled=false" elasticsearch:8.11.0``)

Usage:
    >>> from scraper.services.elasticsearch_service import ElasticSearchService
    >>> es = ElasticSearchService()
    >>> es.create_index()
    >>> es.index_article(article_id=1, title='Test', content='…', embedding=[…], metadata={})
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from django.conf import settings

logger = logging.getLogger('scraper')

INDEX_NAME: str = "news_articles"

_EMBEDDING_DIM: int = getattr(settings, 'EMBEDDING_DIMENSION', 768)

# Index mapping definition
_INDEX_MAPPING: dict[str, Any] = {
    "mappings": {
        "properties": {
            "article_id": {"type": "integer"},
            "title": {
                "type": "text",
                "fields": {"keyword": {"type": "keyword", "ignore_above": 500}},
            },
            "content": {"type": "text"},
            "description": {"type": "text"},
            "url": {"type": "keyword"},
            "source": {"type": "keyword"},
            "author": {"type": "text"},
            "publish_date": {"type": "date", "ignore_malformed": True},
            "scraped_at": {"type": "date"},
            "content_embedding": {
                "type": "dense_vector",
                "dims": _EMBEDDING_DIM,
                "index": True,
                "similarity": "cosine",
            },
        }
    },
    "settings": {
        "number_of_shards": 1,
        "number_of_replicas": 0,
    },
}


class ElasticSearchService:
    """
    Index articles and perform vector search in ElasticSearch.

    Args:
        host: ES host URL (default from ``settings.ELASTICSEARCH_HOST``).
        **kwargs: Extra keyword arguments forwarded to the ES client constructor
                  (e.g. ``basic_auth``, ``ca_certs``).

    Example:
        >>> es = ElasticSearchService()
        >>> es.create_index()
        True
    """

    def __init__(
        self,
        host: str | None = None,
        **kwargs: Any,
    ) -> None:
        self.host = host or getattr(settings, 'ELASTICSEARCH_HOST', 'http://localhost:9200')
        self.client: Any = None
        self._connected: bool = False
        self._init_client(**kwargs)

    # ------------------------------------------------------------------
    # Initialisation
    # ------------------------------------------------------------------

    def _init_client(self, **kwargs: Any) -> None:
        """Create the ES client and test the connection."""
        try:
            from elasticsearch import Elasticsearch

            # Build auth params if credentials are provided
            es_user = getattr(settings, 'ELASTICSEARCH_USER', '')
            es_pass = getattr(settings, 'ELASTICSEARCH_PASSWORD', '')
            if es_user and es_pass and 'basic_auth' not in kwargs:
                kwargs['basic_auth'] = (es_user, es_pass)

            self.client = Elasticsearch(self.host, **kwargs)

            if self.client.ping():
                self._connected = True
                logger.info("Connected to ElasticSearch at %s", self.host)
            else:
                logger.warning("ElasticSearch ping failed at %s", self.host)

        except ImportError:
            logger.error(
                "elasticsearch package is not installed. "
                "Run: pip install elasticsearch"
            )
        except Exception:
            logger.exception("Failed to connect to ElasticSearch at %s", self.host)

    @property
    def is_connected(self) -> bool:
        """Whether the ES client is connected and responsive."""
        return self._connected and self.client is not None

    # ------------------------------------------------------------------
    # Index management
    # ------------------------------------------------------------------

    def create_index(self, delete_existing: bool = False) -> bool:
        """
        Create the ``news_articles`` index with vector mapping.

        Args:
            delete_existing: If ``True``, delete and recreate the index.

        Returns:
            ``True`` if the index was created or already exists.
        """
        if not self.is_connected:
            logger.error("Cannot create index — not connected to ElasticSearch")
            return False

        try:
            index_exists = self.client.indices.exists(index=INDEX_NAME)

            if index_exists and delete_existing:
                logger.warning("Deleting existing index '%s'", INDEX_NAME)
                self.client.indices.delete(index=INDEX_NAME)
                index_exists = False

            if not index_exists:
                self.client.indices.create(index=INDEX_NAME, body=_INDEX_MAPPING)
                logger.info("Created ElasticSearch index '%s'", INDEX_NAME)
            else:
                logger.info("Index '%s' already exists", INDEX_NAME)

            return True
        except Exception:
            logger.exception("Failed to create index '%s'", INDEX_NAME)
            return False

    # ------------------------------------------------------------------
    # Indexing
    # ------------------------------------------------------------------

    def index_article(
        self,
        article_id: int,
        title: str,
        content: str,
        embedding: list[float],
        metadata: dict[str, Any] | None = None,
    ) -> bool:
        """
        Index a single article document.

        Args:
            article_id: Primary key of the ``NewsArticle``.
            title: Article title.
            content: Article content.
            embedding: Embedding vector.
            metadata: Extra fields (``description``, ``url``, ``source``,
                      ``author``, ``publish_date``, ``scraped_at``).

        Returns:
            ``True`` on success.
        """
        if not self.is_connected:
            logger.error("Cannot index article — not connected to ElasticSearch")
            return False

        metadata = metadata or {}
        doc: dict[str, Any] = {
            "article_id": article_id,
            "title": title,
            "content": content[:10000],  # Limit content size for ES
            "description": metadata.get("description", ""),
            "url": metadata.get("url", ""),
            "source": metadata.get("source", ""),
            "author": metadata.get("author", ""),
            "publish_date": metadata.get("publish_date"),
            "scraped_at": metadata.get("scraped_at", datetime.now(timezone.utc).isoformat()),
            "content_embedding": embedding,
        }

        try:
            self.client.index(index=INDEX_NAME, id=str(article_id), document=doc)
            logger.debug("Indexed article %d in ElasticSearch", article_id)
            return True
        except Exception:
            logger.exception("Failed to index article %d", article_id)
            return False

    def bulk_index_articles(self, articles: list[dict[str, Any]]) -> dict[str, int]:
        """
        Bulk-index multiple articles (much faster than one-by-one).

        Each item in *articles* must contain at least ``article_id``, ``title``,
        ``content``, and ``content_embedding``.

        Args:
            articles: List of article dicts.

        Returns:
            ``{'success': int, 'failed': int}``
        """
        if not self.is_connected:
            logger.error("Cannot bulk-index — not connected to ElasticSearch")
            return {'success': 0, 'failed': len(articles)}

        if not articles:
            return {'success': 0, 'failed': 0}

        try:
            from elasticsearch.helpers import bulk

            actions: list[dict[str, Any]] = []
            for article in articles:
                action = {
                    "_index": INDEX_NAME,
                    "_id": str(article["article_id"]),
                    "_source": {
                        "article_id": article["article_id"],
                        "title": article.get("title", ""),
                        "content": article.get("content", "")[:10000],
                        "description": article.get("description", ""),
                        "url": article.get("url", ""),
                        "source": article.get("source", ""),
                        "author": article.get("author", ""),
                        "publish_date": article.get("publish_date"),
                        "scraped_at": article.get("scraped_at", datetime.now(timezone.utc).isoformat()),
                        "content_embedding": article.get("content_embedding", []),
                    },
                }
                actions.append(action)

            success, errors = bulk(self.client, actions, raise_on_error=False)
            failed = len(errors) if isinstance(errors, list) else 0
            logger.info(
                "Bulk indexed %d articles (success=%d, failed=%d)",
                len(articles),
                success,
                failed,
            )
            return {'success': success, 'failed': failed}

        except Exception:
            logger.exception("Bulk indexing failed for %d articles", len(articles))
            return {'success': 0, 'failed': len(articles)}

    # ------------------------------------------------------------------
    # Maintenance
    # ------------------------------------------------------------------

    def delete_old_articles(self, days: int = 30) -> int:
        """
        Delete articles older than *days* from the index.

        Args:
            days: Age threshold in days.

        Returns:
            Number of deleted documents.
        """
        if not self.is_connected:
            logger.error("Cannot delete — not connected to ElasticSearch")
            return 0

        try:
            cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
            body = {
                "query": {
                    "range": {
                        "scraped_at": {"lt": cutoff},
                    }
                }
            }
            result = self.client.delete_by_query(index=INDEX_NAME, body=body)
            deleted = result.get("deleted", 0)
            logger.info("Deleted %d articles older than %d days from ES", deleted, days)
            return deleted
        except Exception:
            logger.exception("Failed to delete old articles from ES")
            return 0
