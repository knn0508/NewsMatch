"""
Models for the MEDIATRENDS autonomous news scraping system.

Active models (Jina AI-powered):
    - NewsSource: news websites to scrape automatically
    - NewsArticle: scraped articles with embeddings
    - UserKeyword: user keyword subscriptions with semantic embeddings
    - SentArticle: delivery tracking

Legacy models (kept for migration compatibility, not used by active code):
    - UserProfile, Keyword, Article, KeywordArticleMatch, Notification
"""

from django.db import models
from django.contrib.auth.models import User


# =============================================================================
# LEGACY MODELS — kept for migration compatibility, no longer used
# =============================================================================


class UserProfile(models.Model):
    """Links a Django User to their Telegram chat for notifications."""

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile', verbose_name="User")
    telegram_chat_id = models.BigIntegerField(unique=True, null=True, blank=True, verbose_name="Telegram Chat ID")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"{self.user.username} - {self.telegram_chat_id}"


class Keyword(models.Model):
    """Legacy keyword model for simple text-based matching."""

    user = models.ForeignKey(User, on_delete=models.CASCADE, verbose_name="User")
    keyword_name = models.CharField(max_length=255, verbose_name="Keyword Name", db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('user', 'keyword_name')
        indexes = [
            models.Index(fields=['user', 'keyword_name']),
        ]

    def __str__(self) -> str:
        return f"{self.user.username} - {self.keyword_name}"


class Article(models.Model):
    """Legacy article model for simple scraping."""

    title = models.CharField(max_length=255, verbose_name="Title", db_index=True)
    content = models.TextField(verbose_name="Content")
    url = models.URLField(unique=True, verbose_name="URL")
    image_url = models.URLField(verbose_name="Image URL", null=True, blank=True)
    date = models.CharField(max_length=100, verbose_name="Date")

    class Meta:
        indexes = [
            models.Index(fields=['url']),
        ]

    def __str__(self) -> str:
        return self.title


class KeywordArticleMatch(models.Model):
    """Legacy model linking keywords to matched articles."""

    keyword = models.ForeignKey(Keyword, on_delete=models.CASCADE, related_name="keyword_article_matches", verbose_name="Keyword")
    article = models.ForeignKey(Article, on_delete=models.CASCADE, related_name="keyword_matches", verbose_name="Article")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('keyword', 'article')
        indexes = [
            models.Index(fields=['keyword', 'article']),
        ]

    def __str__(self) -> str:
        return f"{self.keyword} - {self.article}"


class Notification(models.Model):
    """Legacy notification model for user alerts."""

    NOTIFICATION_STATUS_CHOICES = [
        ('unread', 'Unread'),
        ('read', 'Read'),
        ('archived', 'Archived'),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, verbose_name="User")
    keyword = models.ForeignKey(Keyword, on_delete=models.CASCADE, verbose_name="Keyword")
    article = models.ForeignKey(Article, on_delete=models.CASCADE, verbose_name="Article")
    status = models.CharField(
        max_length=10,
        choices=NOTIFICATION_STATUS_CHOICES,
        default='unread',
        verbose_name="Status"
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Created At")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Updated At")

    class Meta:
        ordering = ['-created_at']
        unique_together = ('user', 'keyword', 'article')
        indexes = [
            models.Index(fields=['user', 'status', '-created_at']),
            models.Index(fields=['user', '-created_at']),
        ]

    def __str__(self) -> str:
        return f"Notification for {self.user.username} - {self.article.title}"


# =============================================================================
# NEW AI-POWERED MODELS (autonomous news scraping system)
# =============================================================================


class NewsSource(models.Model):
    """
    Represents a news website that is scraped automatically by Jina AI.

    Admins add news sources via Django admin panel. The system automatically
    scrapes these sources at the configured interval using Jina AI Reader,
    which requires no manual CSS selectors and adapts to HTML changes.

    Example:
        >>> source = NewsSource.objects.create(
        ...     name="AzeNews",
        ...     url="https://azenews.az",
        ...     is_active=True,
        ...     scrape_interval_hours=1,
        ... )
    """

    SCRAPE_STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('success', 'Success'),
        ('failed', 'Failed'),
    ]

    name = models.CharField(
        max_length=200,
        verbose_name="Source Name",
        help_text="Human-readable name, e.g. 'AzeNews', 'Trend.az'",
    )
    url = models.URLField(
        unique=True,
        verbose_name="Website URL",
        help_text="Homepage URL of the news source",
    )
    is_active = models.BooleanField(
        default=True,
        verbose_name="Active",
        help_text="Enable or disable automatic scraping",
    )
    scrape_interval_hours = models.IntegerField(
        default=1,
        verbose_name="Scrape Interval (hours)",
        help_text="How often to scrape this source",
    )
    last_scraped = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Last Scraped",
    )
    scrape_status = models.CharField(
        max_length=10,
        choices=SCRAPE_STATUS_CHOICES,
        default='pending',
        verbose_name="Scrape Status",
    )
    error_message = models.TextField(
        blank=True,
        default='',
        verbose_name="Error Message",
        help_text="Last error message if scrape failed",
    )
    total_articles_scraped = models.IntegerField(
        default=0,
        verbose_name="Total Articles Scraped",
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Created At")

    class Meta:
        verbose_name = "News Source"
        verbose_name_plural = "News Sources"
        ordering = ['name']

    def __str__(self) -> str:
        status = "✓" if self.is_active else "✗"
        return f"[{status}] {self.name} ({self.url})"


class NewsArticle(models.Model):
    """
    Stores a scraped news article with its embedding vector for semantic search.

    Each article is scraped by Jina AI, processed by LangChain, embedded by
    sentence-transformers, and indexed in ElasticSearch for vector search.

    The ``content_embedding`` field stores a 768-dimensional float vector as a
    JSON list, generated by the ``paraphrase-multilingual-mpnet-base-v2`` model.

    Example:
        >>> article = NewsArticle.objects.create(
        ...     source=source,
        ...     title="Şəki şəhərində yeni park açıldı",
        ...     content="Full article text...",
        ...     url="https://azenews.az/article/123",
        ... )
    """

    source = models.ForeignKey(
        NewsSource,
        on_delete=models.CASCADE,
        related_name='articles',
        verbose_name="News Source",
    )
    title = models.CharField(max_length=500, verbose_name="Title")
    content = models.TextField(verbose_name="Full Content", help_text="Clean article text from Jina AI")
    description = models.TextField(blank=True, default='', verbose_name="Description", help_text="Meta description or summary")
    url = models.URLField(unique=True, db_index=True, verbose_name="Article URL", help_text="Unique article URL (prevents duplicates)")
    article_link = models.URLField(blank=True, default='', verbose_name="Article Link", help_text="Direct link to the original article")
    category = models.CharField(max_length=100, blank=True, default='', db_index=True, verbose_name="Category", help_text="News category (e.g. Nation, Business, Sports)")
    publish_date = models.DateTimeField(null=True, blank=True, db_index=True, verbose_name="Publish Date")
    author = models.CharField(max_length=200, blank=True, default='', verbose_name="Author")
    content_embedding = models.JSONField(
        null=True,
        blank=True,
        verbose_name="Content Embedding",
        help_text="768-dim vector from sentence-transformers, stored as JSON list",
    )
    es_indexed = models.BooleanField(
        default=False,
        verbose_name="ElasticSearch Indexed",
        help_text="Whether this article has been indexed in ElasticSearch",
    )
    es_index_date = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="ES Index Date",
    )
    scraped_at = models.DateTimeField(auto_now_add=True, verbose_name="Scraped At")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Updated At")

    class Meta:
        verbose_name = "News Article"
        verbose_name_plural = "News Articles"
        ordering = ['-publish_date', '-scraped_at']
        indexes = [
            models.Index(fields=['publish_date']),
            models.Index(fields=['source', 'publish_date']),
            models.Index(fields=['es_indexed']),
            models.Index(fields=['category']),
        ]

    def __str__(self) -> str:
        date_str = self.publish_date.strftime('%Y-%m-%d') if self.publish_date else 'No date'
        return f"[{date_str}] {self.title[:80]}"

    @property
    def has_embedding(self) -> bool:
        """Check whether an embedding vector has been generated."""
        from django.conf import settings as django_settings
        dim = getattr(django_settings, 'EMBEDDING_DIMENSION', 768)
        return self.content_embedding is not None and len(self.content_embedding) == dim


class UserKeyword(models.Model):
    """
    A keyword subscription for a Telegram user with its embedding vector.

    When a user sends ``/add_keyword Şəki`` to the Telegram bot, this model
    stores the keyword and its 768-dim embedding. The embedding is used for
    semantic matching against article embeddings, preventing false positives
    (e.g., 'Şəki' city won't match 'şəkil' picture).

    Example:
        >>> kw = UserKeyword.objects.create(user_id=5428705088, keyword="Şəki")
        >>> # Embedding generated asynchronously by Celery task
    """

    user_id = models.BigIntegerField(
        db_index=True,
        verbose_name="Telegram User ID",
        help_text="Telegram user ID (not chat ID)",
    )
    keyword = models.CharField(
        max_length=200,
        verbose_name="Keyword",
        help_text="Search keyword or phrase",
    )
    keyword_embedding = models.JSONField(
        null=True,
        blank=True,
        verbose_name="Keyword Embedding",
        help_text="768-dim vector from sentence-transformers, stored as JSON list",
    )
    keyword_aliases = models.JSONField(
        default=list,
        blank=True,
        verbose_name="Keyword Aliases",
        help_text="Auto-generated translations of the keyword in multiple languages",
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Created At")

    class Meta:
        verbose_name = "User Keyword"
        verbose_name_plural = "User Keywords"
        unique_together = ('user_id', 'keyword')
        indexes = [
            models.Index(fields=['user_id']),
        ]

    def __str__(self) -> str:
        emb = "✓" if self.keyword_embedding else "✗"
        return f"User {self.user_id} → '{self.keyword}' [emb:{emb}]"

    @property
    def has_embedding(self) -> bool:
        """Check whether an embedding vector has been generated."""
        from django.conf import settings as django_settings
        dim = getattr(django_settings, 'EMBEDDING_DIMENSION', 768)
        return self.keyword_embedding is not None and len(self.keyword_embedding) == dim


class SentArticle(models.Model):
    """
    Tracks articles that have been sent to users via Telegram.

    Prevents duplicate sends and records the matched keyword and cosine
    similarity score for each delivery.

    Example:
        >>> sent = SentArticle.objects.create(
        ...     user_id=5428705088,
        ...     article=article,
        ...     matched_keyword="Şəki",
        ...     similarity_score=0.89,
        ... )
    """

    user_id = models.BigIntegerField(
        db_index=True,
        verbose_name="Telegram User ID",
    )
    article = models.ForeignKey(
        NewsArticle,
        on_delete=models.CASCADE,
        related_name='sent_records',
        verbose_name="Article",
    )
    sent_at = models.DateTimeField(auto_now_add=True, verbose_name="Sent At")
    matched_keyword = models.CharField(
        max_length=200,
        blank=True,
        default='',
        verbose_name="Matched Keyword",
        help_text="The keyword that triggered this match",
    )
    similarity_score = models.FloatField(
        default=0.0,
        verbose_name="Similarity Score",
        help_text="Cosine similarity score (0.0 to 1.0)",
    )

    class Meta:
        verbose_name = "Sent Article"
        verbose_name_plural = "Sent Articles"
        unique_together = ('user_id', 'article')
        indexes = [
            models.Index(fields=['user_id', '-sent_at']),
        ]

    def __str__(self) -> str:
        return f"User {self.user_id} ← {self.article.title[:50]} (score: {self.similarity_score:.2f})"
    