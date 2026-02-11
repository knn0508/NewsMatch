"""
Django admin configuration for MEDIATRENDS.

All scraping is powered by Jina AI. Just add a NewsSource URL in the admin
panel and the system scrapes it automatically — no code needed.
"""

from django.contrib import admin

from .models import (
    NewsArticle,
    NewsSource,
    SentArticle,
    UserKeyword,
)


# =============================================================================
# AI-POWERED ADMIN CLASSES
# =============================================================================


@admin.register(NewsSource)
class NewsSourceAdmin(admin.ModelAdmin):
    """Admin for managing news sources scraped by Jina AI."""

    list_display = [
        'name', 'url', 'is_active', 'scrape_status',
        'last_scraped', 'total_articles_scraped',
    ]
    list_filter = ['is_active', 'scrape_status']
    search_fields = ['name', 'url']
    list_editable = ['is_active']
    readonly_fields = ['created_at', 'last_scraped', 'scrape_status', 'error_message', 'total_articles_scraped']
    actions = ['scrape_now', 'activate_sources', 'deactivate_sources']

    fieldsets = (
        (None, {
            'fields': ('name', 'url', 'is_active', 'scrape_interval_hours'),
        }),
        ('Status', {
            'fields': ('scrape_status', 'last_scraped', 'error_message', 'total_articles_scraped', 'created_at'),
            'classes': ('collapse',),
        }),
    )

    @admin.action(description='🔄 Scrape selected sources NOW')
    def scrape_now(self, request, queryset):
        """Trigger immediate scrape for selected sources."""
        from .tasks import scrape_single_source

        count = 0
        for source in queryset:
            scrape_single_source.delay(source.id)
            count += 1
        self.message_user(request, f"Dispatched scrape tasks for {count} source(s).")

    @admin.action(description='✅ Activate selected sources')
    def activate_sources(self, request, queryset):
        updated = queryset.update(is_active=True)
        self.message_user(request, f"Activated {updated} source(s).")

    @admin.action(description='❌ Deactivate selected sources')
    def deactivate_sources(self, request, queryset):
        updated = queryset.update(is_active=False)
        self.message_user(request, f"Deactivated {updated} source(s).")


@admin.register(NewsArticle)
class NewsArticleAdmin(admin.ModelAdmin):
    """Admin for viewing scraped news articles and their ES/embedding status."""

    list_display = [
        'title_short', 'category', 'source', 'article_link_display',
        'publish_date', 'has_embedding', 'es_indexed', 'scraped_at',
    ]
    list_filter = ['source', 'category', 'es_indexed', 'publish_date']
    search_fields = ['title', 'content', 'url', 'category']
    readonly_fields = ['scraped_at', 'updated_at', 'es_index_date']
    date_hierarchy = 'scraped_at'
    actions = ['reindex_elasticsearch', 'regenerate_embeddings']

    fieldsets = (
        (None, {
            'fields': ('source', 'title', 'category', 'url', 'article_link', 'publish_date', 'author'),
        }),
        ('Content', {
            'fields': ('content', 'description'),
            'classes': ('collapse',),
        }),
        ('AI / Search', {
            'fields': ('es_indexed', 'es_index_date'),
            'classes': ('collapse',),
        }),
        ('Timestamps', {
            'fields': ('scraped_at', 'updated_at'),
        }),
    )

    @admin.display(description='Title')
    def title_short(self, obj):
        return obj.title[:80] + '…' if len(obj.title) > 80 else obj.title

    @admin.display(description='Link')
    def article_link_display(self, obj):
        from django.utils.html import format_html
        link = obj.article_link or obj.url
        return format_html('<a href="{}" target="_blank">Open</a>', link)

    @admin.display(description='Embedding', boolean=True)
    def has_embedding(self, obj):
        from django.conf import settings as django_settings
        dim = getattr(django_settings, 'EMBEDDING_DIMENSION', 768)
        return obj.content_embedding is not None and len(obj.content_embedding or []) == dim

    @admin.action(description='🔄 Re-index selected in ElasticSearch')
    def reindex_elasticsearch(self, request, queryset):
        """Clear ES flag so the periodic embedding task re-indexes them."""
        count = queryset.update(es_indexed=False)
        self.message_user(request, f"Marked {count} article(s) for re-indexing.")

    @admin.action(description='🧠 Regenerate embeddings')
    def regenerate_embeddings(self, request, queryset):
        """Clear embeddings so the periodic task regenerates them."""
        count = 0
        for article in queryset:
            article.content_embedding = None
            article.es_indexed = False
            article.save(update_fields=['content_embedding', 'es_indexed'])
            count += 1
        self.message_user(request, f"Cleared embeddings for {count} article(s) — will regenerate on next cycle.")


@admin.register(UserKeyword)
class UserKeywordAdmin(admin.ModelAdmin):
    """Admin for managing user keyword subscriptions with semantic matching."""

    list_display = ['user_id', 'keyword', 'has_embedding_display', 'created_at']
    list_filter = ['created_at']
    search_fields = ['keyword', 'user_id']
    actions = ['regenerate_embeddings']

    @admin.display(description='Embedding', boolean=True)
    def has_embedding_display(self, obj):
        from django.conf import settings as django_settings
        dim = getattr(django_settings, 'EMBEDDING_DIMENSION', 768)
        return obj.keyword_embedding is not None and len(obj.keyword_embedding or []) == dim

    @admin.action(description='🧠 Regenerate keyword embeddings')
    def regenerate_embeddings(self, request, queryset):
        """Regenerate embeddings for selected keywords."""
        from .tasks import generate_keyword_embedding

        count = 0
        for kw in queryset:
            kw.keyword_embedding = None
            kw.save(update_fields=['keyword_embedding'])
            generate_keyword_embedding.delay(kw.id)
            count += 1
        self.message_user(request, f"Dispatched embedding regeneration for {count} keyword(s).")


@admin.register(SentArticle)
class SentArticleAdmin(admin.ModelAdmin):
    """Admin for viewing article delivery history."""

    list_display = ['user_id', 'article_title', 'matched_keyword', 'similarity_score', 'sent_at']
    list_filter = ['sent_at', 'matched_keyword']
    search_fields = ['user_id', 'article__title']
    readonly_fields = ['sent_at']
    date_hierarchy = 'sent_at'

    @admin.display(description='Article')
    def article_title(self, obj):
        if obj.article:
            return obj.article.title[:60] + '…' if len(obj.article.title) > 60 else obj.article.title
        return '—'