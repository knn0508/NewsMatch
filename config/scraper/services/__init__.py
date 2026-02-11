"""
Services package for the MEDIATRENDS autonomous news scraping system.

This package contains the core service classes:

- ``JinaScraperService``: Scrapes websites using Jina AI Reader (FREE)
- ``LangChainProcessor``: Processes and splits articles using LangChain
- ``EmbeddingService``: Generates multilingual embeddings (sentence-transformers)
- ``ElasticSearchService``: Indexes articles and performs vector search
- ``NewsMatcherService``: Matches articles to user keywords semantically
"""

# Lazy imports — each service is imported only when accessed,
# so a missing dependency (e.g. langchain) won't break unrelated commands.


def __getattr__(name: str):
    _mapping = {
        'JinaScraperService': '.jina_scraper',
        'LangChainProcessor': '.langchain_processor',
        'EmbeddingService': '.embedding_service',
        'ElasticSearchService': '.elasticsearch_service',
        'NewsMatcherService': '.news_matcher',
    }
    if name in _mapping:
        import importlib
        module = importlib.import_module(_mapping[name], __package__)
        return getattr(module, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    'JinaScraperService',
    'LangChainProcessor',
    'EmbeddingService',
    'ElasticSearchService',
    'NewsMatcherService',
]
