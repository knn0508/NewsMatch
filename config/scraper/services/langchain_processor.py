"""
LangChain document processing service.

Uses LangChain's ``RecursiveCharacterTextSplitter`` to chunk long articles
into smaller pieces suitable for embedding and indexing.  Short articles
(< 2 000 chars) are left intact.

Usage:
    >>> from scraper.services.langchain_processor import LangChainProcessor
    >>> proc = LangChainProcessor()
    >>> result = proc.process_article({'title': 'Test', 'content': 'Some text...'})
    >>> result['needs_chunking']
    False
"""

from __future__ import annotations

import logging
from typing import Any

try:
    from langchain_text_splitters import RecursiveCharacterTextSplitter
except ImportError:
    from langchain.text_splitter import RecursiveCharacterTextSplitter

try:
    from langchain_core.documents import Document
except ImportError:
    from langchain.schema import Document

logger = logging.getLogger('scraper')

# Threshold (in characters) below which we skip chunking
_CHUNK_THRESHOLD: int = 2000


class LangChainProcessor:
    """
    Process and split long articles using LangChain.

    Args:
        chunk_size: Maximum characters per chunk.
        chunk_overlap: Overlap between consecutive chunks.

    Example:
        >>> proc = LangChainProcessor(chunk_size=1000, chunk_overlap=200)
        >>> doc = proc.process_article({'title': 'T', 'content': 'Long text...'})
    """

    def __init__(self, chunk_size: int = 1000, chunk_overlap: int = 200) -> None:
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            separators=["\n\n", "\n", " ", ""],
            length_function=len,
        )
        logger.debug(
            "LangChainProcessor initialized (chunk_size=%d, overlap=%d)",
            chunk_size,
            chunk_overlap,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def process_article(self, article_data: dict[str, Any]) -> dict[str, Any]:
        """
        Process a single article's content.

        If the combined title + content is shorter than 2 000 characters the
        text is returned as-is (no splitting).  Otherwise it is split into
        overlapping chunks.

        Args:
            article_data: Dict with at least ``title`` and ``content`` keys.

        Returns:
            Dict with keys:
            - ``processed_content``: The full (cleaned) text.
            - ``chunks``: List of chunk strings (empty if no splitting).
            - ``needs_chunking``: Whether the content was split.
        """
        title: str = article_data.get('title', '')
        content: str = article_data.get('content', '')

        # Combine title and content for processing
        combined_text = f"{title}\n\n{content}".strip()

        if not combined_text:
            logger.warning("Empty article received for processing")
            return {
                'processed_content': '',
                'chunks': [],
                'needs_chunking': False,
            }

        if len(combined_text) < _CHUNK_THRESHOLD:
            logger.debug(
                "Article '%s' is short (%d chars) — no chunking needed",
                title[:50],
                len(combined_text),
            )
            return {
                'processed_content': combined_text,
                'chunks': [],
                'needs_chunking': False,
            }

        # Split into overlapping chunks
        chunks = self.text_splitter.split_text(combined_text)
        logger.info(
            "Article '%s' split into %d chunks (%d chars total)",
            title[:50],
            len(chunks),
            len(combined_text),
        )
        return {
            'processed_content': combined_text,
            'chunks': chunks,
            'needs_chunking': True,
        }

    def create_langchain_documents(self, articles: list[dict[str, Any]]) -> list[Document]:
        """
        Convert a list of article dicts into LangChain ``Document`` objects.

        Each document's ``page_content`` is the full text.  Metadata includes
        ``title``, ``url``, ``source``, ``publish_date``, and ``author``.

        Args:
            articles: List of article dicts (from Jina scraper or DB).

        Returns:
            List of LangChain Document objects.
        """
        documents: list[Document] = []
        for article in articles:
            content = article.get('content', '')
            if not content:
                continue

            doc = Document(
                page_content=f"{article.get('title', '')}\n\n{content}".strip(),
                metadata={
                    'title': article.get('title', ''),
                    'url': article.get('url', ''),
                    'source': article.get('source', ''),
                    'publish_date': str(article.get('publish_date', '')),
                    'author': article.get('author', ''),
                },
            )
            documents.append(doc)

        logger.info("Created %d LangChain documents from %d articles", len(documents), len(articles))
        return documents
