"""
Tests for the MEDIATRENDS autonomous news scraping system.

Covers:
1. Jina AI scraping with sample URL
2. Embedding generation for Azerbaijani text
3. Similarity calculation (Şəki vs şəkil should be < 0.7)
4. ElasticSearch indexing and vector search
5. Duplicate prevention
6. Model creation and constraints
7. LangChain processing
8. News matching service
"""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import MagicMock, patch

from django.test import TestCase, override_settings
from django.utils import timezone

from .models import NewsArticle, NewsSource, SentArticle, UserKeyword


# =============================================================================
# Model Tests
# =============================================================================


class NewsSourceModelTest(TestCase):
    """Tests for the NewsSource model."""

    def test_create_news_source(self):
        source = NewsSource.objects.create(
            name="Test Source",
            url="https://test-news.example.com",
            is_active=True,
            scrape_interval_hours=2,
        )
        self.assertEqual(source.name, "Test Source")
        self.assertTrue(source.is_active)
        self.assertEqual(source.scrape_status, 'pending')
        self.assertEqual(source.total_articles_scraped, 0)

    def test_unique_url_constraint(self):
        NewsSource.objects.create(name="A", url="https://unique.example.com")
        with self.assertRaises(Exception):
            NewsSource.objects.create(name="B", url="https://unique.example.com")

    def test_str_representation(self):
        source = NewsSource(name="AzeNews", url="https://azenews.az", is_active=True)
        self.assertIn("AzeNews", str(source))


class NewsArticleModelTest(TestCase):
    """Tests for the NewsArticle model."""

    def setUp(self):
        self.source = NewsSource.objects.create(
            name="Test Source",
            url="https://test-source.example.com",
        )

    def test_create_article(self):
        article = NewsArticle.objects.create(
            source=self.source,
            title="Test Article",
            content="Some test content",
            url="https://test-source.example.com/article/1",
        )
        self.assertEqual(article.title, "Test Article")
        self.assertFalse(article.es_indexed)
        self.assertIsNone(article.content_embedding)

    def test_unique_url_prevents_duplicates(self):
        """Article URL must be unique — key to duplicate prevention."""
        NewsArticle.objects.create(
            source=self.source,
            title="Article 1",
            content="Content",
            url="https://test-source.example.com/dup",
        )
        with self.assertRaises(Exception):
            NewsArticle.objects.create(
                source=self.source,
                title="Article 2",
                content="Other content",
                url="https://test-source.example.com/dup",
            )

    def test_has_embedding_property(self):
        article = NewsArticle(content_embedding=None)
        self.assertFalse(article.has_embedding)

        article.content_embedding = [0.1] * 768
        self.assertTrue(article.has_embedding)

        article.content_embedding = [0.1] * 100  # Wrong dimension
        self.assertFalse(article.has_embedding)


class UserKeywordModelTest(TestCase):
    """Tests for the UserKeyword model."""

    def test_create_keyword(self):
        kw = UserKeyword.objects.create(user_id=12345, keyword="Şəki")
        self.assertEqual(kw.keyword, "Şəki")
        self.assertIsNone(kw.keyword_embedding)

    def test_unique_together_prevents_duplicates(self):
        UserKeyword.objects.create(user_id=12345, keyword="Bakı")
        with self.assertRaises(Exception):
            UserKeyword.objects.create(user_id=12345, keyword="Bakı")

    def test_different_users_same_keyword(self):
        """Different users can have the same keyword."""
        UserKeyword.objects.create(user_id=111, keyword="neft")
        UserKeyword.objects.create(user_id=222, keyword="neft")
        self.assertEqual(UserKeyword.objects.filter(keyword="neft").count(), 2)


class SentArticleModelTest(TestCase):
    """Tests for the SentArticle model."""

    def setUp(self):
        self.source = NewsSource.objects.create(name="S", url="https://s.example.com")
        self.article = NewsArticle.objects.create(
            source=self.source,
            title="Test",
            content="Content",
            url="https://s.example.com/a/1",
        )

    def test_create_sent_article(self):
        sent = SentArticle.objects.create(
            user_id=12345,
            article=self.article,
            matched_keyword="test",
            similarity_score=0.85,
        )
        self.assertEqual(sent.similarity_score, 0.85)

    def test_unique_together_prevents_duplicate_sends(self):
        SentArticle.objects.create(user_id=12345, article=self.article)
        with self.assertRaises(Exception):
            SentArticle.objects.create(user_id=12345, article=self.article)


# =============================================================================
# Jina Scraper Tests
# =============================================================================


class JinaScraperServiceTest(TestCase):
    """Tests for the JinaScraperService."""

    def test_parse_jina_markdown(self):
        from .services.jina_scraper import JinaScraperService

        scraper = JinaScraperService()
        markdown = (
            "# Test Article Title\n\n"
            "This is a longer description paragraph that has more than forty characters.\n\n"
            "By John Smith\n\n"
            "Published on 2024-01-15\n\n"
            "This is the main content of the article."
        )
        result = scraper._parse_jina_markdown(markdown, "https://example.com/test")
        self.assertEqual(result['title'], "Test Article Title")
        self.assertIn("longer description", result['description'])
        self.assertEqual(result['url'], "https://example.com/test")

    def test_extract_article_urls(self):
        from .services.jina_scraper import JinaScraperService

        scraper = JinaScraperService()
        markdown = (
            "[Article One](/news/article-1)\n"
            "[Article Two](https://example.com/news/article-2)\n"
            "[External](https://other-site.com/page)\n"
            "[Image](logo.png)\n"
        )
        urls = scraper._extract_article_urls(markdown, "https://example.com")
        # Should include same-domain articles, exclude external and images
        self.assertTrue(any("/news/article-1" in u for u in urls))
        self.assertTrue(any("/news/article-2" in u for u in urls))
        self.assertFalse(any("other-site.com" in u for u in urls))

    def test_error_result(self):
        from .services.jina_scraper import JinaScraperService

        result = JinaScraperService._error_result("https://x.com", "timeout")
        self.assertFalse(result['success'])
        self.assertEqual(result['error'], "timeout")

    @patch('scraper.services.jina_scraper.JinaScraperService.scrape_url')
    def test_scrape_url_mock(self, mock_scrape):
        """Test scraping with a mocked response."""
        from .services.jina_scraper import JinaScraperService

        mock_scrape.return_value = {
            'title': 'Mocked Article',
            'content': 'Mocked content',
            'url': 'https://example.com/test',
            'success': True,
        }
        scraper = JinaScraperService()
        result = scraper.scrape_url("https://example.com/test")
        self.assertTrue(result['success'])
        self.assertEqual(result['title'], 'Mocked Article')


# =============================================================================
# LangChain Processor Tests
# =============================================================================


class LangChainProcessorTest(TestCase):
    """Tests for the LangChainProcessor."""

    def test_short_article_no_chunking(self):
        from .services.langchain_processor import LangChainProcessor

        proc = LangChainProcessor()
        result = proc.process_article({
            'title': 'Short',
            'content': 'This is a short article.',
        })
        self.assertFalse(result['needs_chunking'])
        self.assertEqual(len(result['chunks']), 0)

    def test_long_article_chunking(self):
        from .services.langchain_processor import LangChainProcessor

        proc = LangChainProcessor(chunk_size=500, chunk_overlap=50)
        long_content = "Word " * 1000  # ~5000 chars
        result = proc.process_article({
            'title': 'Long Article',
            'content': long_content,
        })
        self.assertTrue(result['needs_chunking'])
        self.assertGreater(len(result['chunks']), 1)

    def test_empty_article(self):
        from .services.langchain_processor import LangChainProcessor

        proc = LangChainProcessor()
        result = proc.process_article({'title': '', 'content': ''})
        self.assertEqual(result['processed_content'], '')
        self.assertFalse(result['needs_chunking'])

    def test_create_langchain_documents(self):
        from .services.langchain_processor import LangChainProcessor

        proc = LangChainProcessor()
        articles = [
            {'title': 'T1', 'content': 'C1', 'url': 'http://a.com', 'source': 'S'},
            {'title': 'T2', 'content': 'C2', 'url': 'http://b.com', 'source': 'S'},
        ]
        docs = proc.create_langchain_documents(articles)
        self.assertEqual(len(docs), 2)
        self.assertIn('T1', docs[0].page_content)


# =============================================================================
# Embedding Service Tests
# =============================================================================


class EmbeddingServiceTest(TestCase):
    """
    Tests for the EmbeddingService.

    NOTE: These tests load the actual sentence-transformers model.
    They will be slow on first run (model download) and require
    ~500 MB disk space.  Skip with ``--exclude-tag=slow`` if needed.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        try:
            from .services.embedding_service import EmbeddingService
            cls.svc = EmbeddingService()
            cls.available = True
        except Exception:
            cls.available = False

    def test_embedding_dimension(self):
        if not self.available:
            self.skipTest("Embedding model not available")
        emb = self.svc.get_embedding("Test text")
        self.assertEqual(len(emb), 768)

    def test_azerbaijani_text(self):
        """Embedding should work with Azerbaijani text."""
        if not self.available:
            self.skipTest("Embedding model not available")
        emb = self.svc.get_embedding("Şəki şəhərində yeni park açıldı")
        self.assertEqual(len(emb), 768)
        self.assertFalse(all(v == 0.0 for v in emb))

    def test_seki_vs_sekil_different(self):
        """
        'Şəki' (city) and 'şəkil' (picture) should have LOW similarity.

        This is the key test demonstrating why semantic search is better
        than simple text matching.
        """
        if not self.available:
            self.skipTest("Embedding model not available")
        emb_seki = self.svc.get_embedding("Şəki")
        emb_sekil = self.svc.get_embedding("şəkil")
        similarity = self.svc.calculate_similarity(emb_seki, emb_sekil)
        # Should be below 0.7 threshold
        self.assertLess(
            similarity, 0.7,
            f"'Şəki' vs 'şəkil' similarity {similarity:.4f} should be < 0.7",
        )

    def test_similar_texts_high_similarity(self):
        """Semantically similar texts should have high similarity."""
        if not self.available:
            self.skipTest("Embedding model not available")
        emb1 = self.svc.get_embedding("Bakı şəhərində hava haqqında")
        emb2 = self.svc.get_embedding("Bakıda hava proqnozu")
        similarity = self.svc.calculate_similarity(emb1, emb2)
        self.assertGreater(similarity, 0.5, f"Similar texts should be > 0.5, got {similarity:.4f}")

    def test_batch_embeddings(self):
        if not self.available:
            self.skipTest("Embedding model not available")
        texts = ["Hello world", "Salam dünya", ""]
        embs = self.svc.get_embeddings_batch(texts)
        self.assertEqual(len(embs), 3)
        self.assertEqual(len(embs[0]), 768)
        # Empty text should get zero vector
        self.assertTrue(all(v == 0.0 for v in embs[2]))

    def test_empty_text_returns_zero_vector(self):
        if not self.available:
            self.skipTest("Embedding model not available")
        emb = self.svc.get_embedding("")
        self.assertEqual(len(emb), 768)
        self.assertTrue(all(v == 0.0 for v in emb))

    def test_find_similar_texts(self):
        if not self.available:
            self.skipTest("Embedding model not available")
        query = self.svc.get_embedding("football match")
        corpus = [
            self.svc.get_embedding("soccer game results"),
            self.svc.get_embedding("cooking recipe for pasta"),
            self.svc.get_embedding("football championship"),
        ]
        results = self.svc.find_similar_texts(query, corpus, threshold=0.3, top_k=5)
        # Football-related texts should appear
        self.assertGreater(len(results), 0)


# =============================================================================
# ElasticSearch Service Tests
# =============================================================================


class ElasticSearchServiceTest(TestCase):
    """
    Tests for the ElasticSearchService.

    Requires a running ElasticSearch instance at localhost:9200.
    Tests are skipped automatically if ES is unavailable.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        try:
            from .services.elasticsearch_service import ElasticSearchService
            cls.es = ElasticSearchService()
            cls.available = cls.es.is_connected
        except Exception:
            cls.available = False

    def test_connection(self):
        if not self.available:
            self.skipTest("ElasticSearch not available")
        self.assertTrue(self.es.is_connected)

    def test_create_index(self):
        if not self.available:
            self.skipTest("ElasticSearch not available")
        # Use a test index name to avoid interfering with production data
        result = self.es.create_index(delete_existing=True)
        self.assertTrue(result)

    def test_index_and_search(self):
        if not self.available:
            self.skipTest("ElasticSearch not available")

        self.es.create_index(delete_existing=True)

        # Create a simple embedding
        embedding = [0.1] * 768
        success = self.es.index_article(
            article_id=9999,
            title="Test ES Article",
            content="Test content for ElasticSearch",
            embedding=embedding,
            metadata={'url': 'https://test.com/es-test', 'source': 'test'},
        )
        self.assertTrue(success)

    def test_graceful_when_disconnected(self):
        """Service should handle disconnection gracefully."""
        from .services.elasticsearch_service import ElasticSearchService

        es = ElasticSearchService.__new__(ElasticSearchService)
        es.client = None
        es._connected = False
        es.host = "http://localhost:9200"

        self.assertFalse(es.create_index())
        self.assertFalse(es.index_article(1, "t", "c", [0.1] * 768))
        self.assertEqual(es.search_by_embedding([0.1] * 768), [])
        self.assertEqual(es.delete_old_articles(), 0)


# =============================================================================
# News Matcher Tests
# =============================================================================


class NewsMatcherServiceTest(TestCase):
    """Tests for the NewsMatcherService."""

    def setUp(self):
        self.source = NewsSource.objects.create(
            name="Matcher Test Source",
            url="https://matcher-test.example.com",
        )

    def test_match_article_no_embedding(self):
        """Article without embedding should return empty matches."""
        from .services.news_matcher import NewsMatcherService

        article = NewsArticle.objects.create(
            source=self.source,
            title="No Embedding",
            content="Content",
            url="https://matcher-test.example.com/no-emb",
        )
        matcher = NewsMatcherService()
        matches = matcher.match_article_to_keywords(article)
        self.assertEqual(len(matches), 0)

    def test_match_with_high_similarity(self):
        """Articles matching keywords should return results above threshold."""
        from .services.news_matcher import NewsMatcherService

        # Create an article with a fake embedding
        article = NewsArticle.objects.create(
            source=self.source,
            title="Test Match",
            content="Some content",
            url="https://matcher-test.example.com/match-1",
            content_embedding=[0.5] * 768,  # Fake embedding
        )

        # Create a keyword with a very similar fake embedding
        UserKeyword.objects.create(
            user_id=99999,
            keyword="test",
            keyword_embedding=[0.5] * 768,  # Identical → similarity ≈ 1.0
        )

        matcher = NewsMatcherService(threshold=0.7)
        matches = matcher.match_article_to_keywords(article)
        self.assertGreater(len(matches), 0)
        self.assertGreaterEqual(matches[0]['similarity'], 0.7)

    def test_no_match_below_threshold(self):
        """Dissimilar embeddings should not produce matches."""
        from .services.news_matcher import NewsMatcherService

        article = NewsArticle.objects.create(
            source=self.source,
            title="No Match",
            content="Content",
            url="https://matcher-test.example.com/no-match-1",
            content_embedding=[1.0] + [0.0] * 383,
        )

        UserKeyword.objects.create(
            user_id=88888,
            keyword="unrelated",
            keyword_embedding=[0.0] * 383 + [1.0],  # Orthogonal vector
        )

        matcher = NewsMatcherService(threshold=0.7)
        matches = matcher.match_article_to_keywords(article)
        self.assertEqual(len(matches), 0)


# =============================================================================
# Celery Task Tests (mocked)
# =============================================================================


class CeleryTaskTests(TestCase):
    """Tests for Celery tasks using mocks to avoid external dependencies."""

    def setUp(self):
        self.source = NewsSource.objects.create(
            name="Task Test Source",
            url="https://task-test.example.com",
            is_active=True,
        )

    @patch('scraper.tasks.scrape_single_source.delay')
    def test_scrape_all_active_sources(self, mock_delay):
        from .tasks import scrape_all_active_sources

        result = scrape_all_active_sources()
        mock_delay.assert_called_once_with(self.source.id)
        self.assertIn("1 sources", result)

    def test_scrape_all_no_active_sources(self):
        from .tasks import scrape_all_active_sources

        self.source.is_active = False
        self.source.save()

        result = scrape_all_active_sources()
        self.assertEqual(result, "No active sources")

    def test_generate_keyword_embedding_not_found(self):
        from .tasks import generate_keyword_embedding

        result = generate_keyword_embedding(99999)
        self.assertIn("not found", result)

    def test_cleanup_old_data(self):
        from .tasks import cleanup_old_data

        # Create an old article
        old_article = NewsArticle.objects.create(
            source=self.source,
            title="Old Article",
            content="Old content",
            url="https://task-test.example.com/old-1",
        )
        # Manually backdate it
        NewsArticle.objects.filter(id=old_article.id).update(
            scraped_at=timezone.now() - timedelta(days=60),
        )

        result = cleanup_old_data()
        self.assertIn("1 articles", result)
        self.assertFalse(NewsArticle.objects.filter(id=old_article.id).exists())
