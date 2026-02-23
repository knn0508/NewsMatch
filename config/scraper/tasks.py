"""
Celery tasks for the MEDIATRENDS autonomous news scraping system.

All scraping is powered by Jina AI Reader — no manual BeautifulSoup
scrapers needed. Just add a news source URL in Django admin and the
system scrapes it automatically.

Independent periodic tasks (no chaining — each runs on its own schedule):
    1. scrape_all_active_sources  → scrape_single_source(source_id)
       Only scrapes & saves articles to DB.
    2. generate_article_embeddings
       Picks up articles without embeddings, generates them + ES index.
    3. match_and_notify_users
       Matches embedded articles to user keywords, sends Telegram.
    4. cleanup_old_data
       Daily housekeeping.
"""

from __future__ import annotations

import logging
import re
from datetime import timedelta
from typing import Any

from celery import shared_task
from django.utils import timezone

from .models import (
    NewsArticle,
    NewsSource,
    SentArticle,
    UserKeyword,
)

logger = logging.getLogger('scraper')


# =============================================================================
# AI-POWERED TASKS (autonomous news scraping via Jina AI)
# =============================================================================


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def scrape_all_active_sources(self) -> str:
    """
    Scheduled task: scrape every active ``NewsSource``.

    Dispatches ``scrape_single_source`` for each active source.  Called
    automatically by Celery Beat every hour.

    Returns:
        Summary string.
    """
    active_sources = NewsSource.objects.filter(is_active=True)
    count = active_sources.count()

    if count == 0:
        logger.info("No active news sources to scrape")
        return "No active sources"

    dispatched = 0
    skipped = 0
    now = timezone.now()

    for source in active_sources:
        # Respect per-source scrape_interval_hours
        if source.last_scraped:
            next_scrape = source.last_scraped + timedelta(hours=source.scrape_interval_hours)
            if now < next_scrape:
                logger.debug(
                    "Skipping %s — next scrape at %s",
                    source.name, next_scrape.isoformat(),
                )
                skipped += 1
                continue

        scrape_single_source.delay(source.id)
        dispatched += 1

    logger.info(
        "Dispatched %d scrape tasks (%d skipped due to interval) out of %d active sources",
        dispatched, skipped, count,
    )
    return f"Dispatched {dispatched} tasks, skipped {skipped}"


@shared_task(bind=True, max_retries=3, default_retry_delay=120)
def scrape_single_source(self, source_id: int) -> str:
    """
    Scrape one news source using Jina AI Reader.

    1. Fetches the source homepage via Jina AI.
    2. Extracts article links.
    3. Scrapes each article.
    4. Saves new articles to the database (skips duplicates).
    5. Dispatches ``process_new_article`` for each new article.

    Args:
        source_id: PK of the ``NewsSource`` to scrape.

    Returns:
        Summary string.
    """
    try:
        source = NewsSource.objects.get(id=source_id)
    except NewsSource.DoesNotExist:
        logger.error("NewsSource %d not found", source_id)
        return f"Source {source_id} not found"

    logger.info("Scraping source: %s (%s)", source.name, source.url)

    try:
        from .services.jina_scraper import JinaScraperService

        scraper = JinaScraperService()
        articles_data = scraper.scrape_multiple_articles(source.url)

        new_count = 0
        for article_data in articles_data:
            # Duplicate check — skip if URL already exists
            article_url = article_data.get('url', '')
            if not article_url:
                continue

            # Skip junk entries: title is a media filename or hash
            title = article_data.get('title', '')
            if re.search(r'\.(webp|jpg|jpeg|png|gif|svg|avif|mp4|pdf)$', title, re.IGNORECASE):
                logger.debug("Skipping article with media filename as title: %s", title)
                continue
            if re.fullmatch(r'[a-f0-9]{10,}(\.[a-z]{2,5})?', title, re.IGNORECASE):
                logger.debug("Skipping article with hash-like title: %s", title)
                continue

            if NewsArticle.objects.filter(url=article_url).exists():
                logger.debug("Skipping duplicate article: %s", article_url)
                continue

            # Parse publish date
            publish_date = _parse_date(article_data.get('publish_date'))

            # Create the article
            article = NewsArticle.objects.create(
                source=source,
                title=article_data.get('title', '')[:500],
                content=article_data.get('content', ''),
                description=article_data.get('description', '')[:1000],
                url=article_url,
                article_link=article_data.get('article_link', article_url),
                category=article_data.get('category', '')[:100],
                publish_date=publish_date,
                author=article_data.get('author', '')[:200],
            )
            new_count += 1
            logger.info("Created article %d: %s", article.id, article.title[:60])

        # Update source metadata
        source.last_scraped = timezone.now()
        source.scrape_status = 'success'
        source.error_message = ''
        source.total_articles_scraped += new_count
        source.save(update_fields=[
            'last_scraped', 'scrape_status', 'error_message', 'total_articles_scraped',
        ])

        msg = f"Scraped {source.name}: {new_count} new articles from {len(articles_data)} found"
        logger.info(msg)

        # Immediately trigger embedding generation + ES indexing for new articles
        if new_count > 0:
            generate_article_embeddings.delay(batch_size=new_count + 10)
            logger.info(
                "Dispatched immediate embedding generation for %d new articles from %s",
                new_count, source.name,
            )

        return msg

    except Exception as exc:
        logger.exception("Failed to scrape source %s", source.name)
        source.scrape_status = 'failed'
        source.error_message = str(exc)[:500]
        source.save(update_fields=['scrape_status', 'error_message'])

        # Retry with exponential back-off
        raise self.retry(exc=exc)


# =============================================================================
# TASK 2 — EMBEDDING GENERATION (independent periodic task)
# =============================================================================


@shared_task
def generate_article_embeddings(batch_size: int = 50) -> str:
    """
    Periodic task: generate embeddings for articles that don't have one yet.

    Picks up ``NewsArticle`` rows where ``content_embedding`` is NULL,
    generates the embedding via LangChain + sentence-transformers, and
    indexes them in ElasticSearch.

    Runs independently of the scraping task so scraping is never blocked.

    Args:
        batch_size: Max articles to process per run (default 50).

    Returns:
        Summary string.
    """
    articles = list(
        NewsArticle.objects.filter(content_embedding__isnull=True)
        .order_by('scraped_at')[:batch_size]
    )

    if not articles:
        logger.debug("No articles need embeddings")
        return "No articles need embeddings"

    logger.info("Generating embeddings for %d articles", len(articles))

    from .services.langchain_processor import LangChainProcessor
    from .services.embedding_service import EmbeddingService

    processor = LangChainProcessor()
    embedding_svc = EmbeddingService()

    success_count = 0
    es_count = 0

    for article in articles:
        try:
            # LangChain processing
            processed = processor.process_article({
                'title': article.title,
                'content': article.content,
            })
            text_for_embedding = processed['processed_content']

            # Generate embedding
            embedding = embedding_svc.get_embedding(text_for_embedding)

            if not embedding or all(v == 0.0 for v in embedding):
                logger.warning("Zero embedding for article %d — skipping", article.id)
                continue

            article.content_embedding = embedding
            article.save(update_fields=['content_embedding'])
            success_count += 1
            logger.info("Embedding saved for article %d", article.id)

            # Index in ElasticSearch (graceful — don't fail the whole batch)
            try:
                from .services.elasticsearch_service import ElasticSearchService

                es_service = ElasticSearchService()
                if es_service.is_connected:
                    indexed = es_service.index_article(
                        article_id=article.id,
                        title=article.title,
                        content=article.content,
                        embedding=embedding,
                        metadata={
                            'description': article.description,
                            'url': article.url,
                            'source': article.source.name,
                            'author': article.author,
                            'publish_date': (
                                article.publish_date.isoformat()
                                if article.publish_date else None
                            ),
                            'scraped_at': (
                                article.scraped_at.isoformat()
                                if article.scraped_at else None
                            ),
                        },
                    )
                    if indexed:
                        article.es_indexed = True
                        article.es_index_date = timezone.now()
                        article.save(update_fields=['es_indexed', 'es_index_date'])
                        es_count += 1
                else:
                    logger.warning(
                        "ElasticSearch unavailable — article %d not indexed",
                        article.id,
                    )
            except Exception:
                logger.exception(
                    "ES indexing failed for article %d (non-fatal)", article.id
                )

        except Exception:
            logger.exception("Embedding failed for article %d", article.id)

    msg = (
        f"Embeddings: {success_count}/{len(articles)} generated, "
        f"{es_count} indexed in ES"
    )
    logger.info(msg)
    return msg


# =============================================================================
# TASK 3 — KEYWORD MATCHING & NOTIFICATION (independent periodic task)
# =============================================================================


@shared_task
def match_and_notify_users(lookback_hours: int = 24) -> str:
    """
    Periodic task: match recent embedded articles to user keywords and send
    Telegram notifications.

    Scans articles from the last ``lookback_hours`` that already have
    embeddings, compares them to every user keyword, and dispatches
    ``send_article_to_user`` for new matches.

    Duplicate sends are prevented by ``SentArticle`` — if an article was
    already sent to a user, it is skipped.

    Runs independently of scraping and embedding tasks.

    Args:
        lookback_hours: How far back to look for articles (default 24h).

    Returns:
        Summary string.
    """
    cutoff = timezone.now() - timedelta(hours=lookback_hours)
    articles = list(
        NewsArticle.objects.filter(
            scraped_at__gte=cutoff,
        ).select_related('source')
    )

    if not articles:
        logger.debug("No embedded articles to match in the last %dh", lookback_hours)
        return "No articles to match"

    from .services.news_matcher import NewsMatcherService

    matcher = NewsMatcherService()
    dispatched = 0
    skipped = 0

    for article in articles:
        try:
            matches = matcher.match_article_to_keywords(article)

            for match in matches:
                # Skip if already sent (avoid dispatching unnecessary tasks)
                if SentArticle.objects.filter(
                    user_id=match['user_id'],
                    article_id=article.id,
                ).exists():
                    skipped += 1
                    continue

                send_article_to_user.delay(
                    user_id=match['user_id'],
                    article_id=article.id,
                    matched_keyword=match['keyword'],
                    similarity_score=match['similarity'],
                    evidence=match.get('evidence', ''),
                    keyword_in_text=match.get('keyword_in_text', False),
                )
                dispatched += 1

        except Exception:
            logger.exception("Matching failed for article %d", article.id)

    msg = (
        f"Matching done: {len(articles)} articles scanned, "
        f"{dispatched} notifications dispatched, {skipped} duplicates skipped"
    )
    logger.info(msg)
    return msg


@shared_task(bind=True, max_retries=2, default_retry_delay=10)
def send_article_to_user(
    self,
    user_id: int,
    article_id: int,
    matched_keyword: str = '',
    similarity_score: float = 0.0,
    evidence: str = '',
    keyword_in_text: bool = False,
) -> str:
    """
    Send a matched article to a user via Telegram and record in ``SentArticle``.

    Prevents duplicate sends using the ``unique_together`` constraint.

    Args:
        user_id: Telegram user ID.
        article_id: PK of the ``NewsArticle``.
        matched_keyword: The keyword that triggered the match.
        similarity_score: Cosine similarity score.
        evidence: Human-readable explanation of where the match was found.
        keyword_in_text: Whether the keyword literally appears in the article.

    Returns:
        Summary string.
    """
    # Replace the API key with a placeholder comment
        api_url = f"https://api.telegram.org/bot<TELEGRAM_BOT_TOKEN>/sendMessage"
    # Check for duplicate
    if SentArticle.objects.filter(user_id=user_id, article_id=article_id).exists():
        logger.debug("Already sent article %d to user %d — skipping", article_id, user_id)
        return f"Duplicate — article {article_id} already sent to user {user_id}"

    try:
        article = NewsArticle.objects.select_related('source').get(id=article_id)
    except NewsArticle.DoesNotExist:
        logger.error("NewsArticle %d not found for sending", article_id)
        return f"Article {article_id} not found"

    # Format Telegram message with evidence
    description_preview = article.description[:200] if article.description else article.content[:200]
    match_type = "✅ Direct text match" if keyword_in_text else "🔍 Semantic match"

    message = (
        f"🔔 <b>New Article Match!</b>\n\n"
        f"📰 <b>{article.title}</b>\n\n"
        f"🔑 Keyword: <b>{matched_keyword}</b>\n"
        f"📊 Similarity: <b>{similarity_score:.0%}</b>\n"
        f"🏷 Match type: {match_type}\n"
        f"📅 Source: {article.source.name}\n\n"
    )

    # Add evidence section showing WHERE the match was found
    if evidence:
        message += f"🔎 <b>Why this matched:</b>\n<i>{evidence[:300]}</i>\n\n"

    message += (
        f"📝 {description_preview}…\n\n"
        f"🔗 <a href=\"{article.url}\">Read full article</a>"
    )

    # Send via Telegram
    try:
        from django.conf import settings as django_settings

        bot_token = getattr(django_settings, 'TG_BOT_TOKEN', '')
        if not bot_token:
            logger.error("No Telegram bot token configured")
            return "No bot token"

        api_url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        resp = http_requests.post(
            api_url,
            json={
                'chat_id': user_id,
                'text': message,
                'parse_mode': 'HTML',
                'disable_web_page_preview': False,
            },
            timeout=10,
        )
        resp_data = resp.json()

        if not resp_data.get('ok'):
            logger.warning(
                "Telegram API error for user %d: %s",
                user_id,
                resp_data.get('description', 'unknown'),
            )
        else:
            logger.info("Sent article %d to user %d via Telegram", article_id, user_id)

    except Exception:
        logger.exception("Failed to send Telegram message to user %d", user_id)
        raise self.retry(exc=Exception("Telegram send failed"))

    # Record delivery
    SentArticle.objects.get_or_create(
        user_id=user_id,
        article=article,
        defaults={
            'matched_keyword': matched_keyword,
            'similarity_score': similarity_score,
        },
    )

    return f"Sent article {article_id} to user {user_id} (keyword='{matched_keyword}', score={similarity_score:.2f})"


@shared_task
def generate_keyword_embedding(keyword_id: int) -> str:
    """
    Generate translations (aliases) and embedding for a ``UserKeyword``.

    1. Translates the keyword into multiple languages via deep-translator.
    2. Generates the embedding (kept for potential future use).
    3. Checks recent articles for immediate matches using the new aliases.

    Args:
        keyword_id: PK of the ``UserKeyword``.

    Returns:
        Summary string.
    """
    try:
        user_keyword = UserKeyword.objects.get(id=keyword_id)
    except UserKeyword.DoesNotExist:
        logger.error("UserKeyword %d not found", keyword_id)
        return f"Keyword {keyword_id} not found"

    logger.info(
        "Generating aliases + embedding for keyword '%s' (user %d)",
        user_keyword.keyword,
        user_keyword.user_id,
    )

    # ── Step 1: Generate translated aliases ──
    try:
        from .services.translation_service import TranslationService

        trans_svc = TranslationService()
        aliases = trans_svc.update_keyword_aliases(user_keyword)
        logger.info(
            "Generated %d aliases for '%s': %s",
            len(aliases), user_keyword.keyword, aliases,
        )
    except Exception:
        logger.exception("Alias generation failed for keyword '%s'", user_keyword.keyword)
        # Continue — text matching still works with just the original keyword

    # ── Step 2: Generate embedding (kept for future use) ──
    try:
        from .services.embedding_service import EmbeddingService

        svc = EmbeddingService()
        enriched_text = f"News article about {user_keyword.keyword}"
        embedding = svc.get_embedding(enriched_text)

        if embedding and not all(v == 0.0 for v in embedding):
            user_keyword.keyword_embedding = embedding
            user_keyword.save(update_fields=['keyword_embedding'])
            logger.info("Embedding saved for keyword '%s'", user_keyword.keyword)
    except Exception:
        logger.exception("Embedding generation failed for keyword '%s'", user_keyword.keyword)

    # ── Step 3: Check recent articles for immediate matches ──
    try:
        from .services.news_matcher import NewsMatcherService

        matcher = NewsMatcherService()
        matches = matcher.match_keyword_to_articles(user_keyword, recent_days=7)
        for match_item in matches:
            send_article_to_user.delay(
                user_id=user_keyword.user_id,
                article_id=match_item['article_id'],
                matched_keyword=user_keyword.keyword,
                similarity_score=match_item['similarity'],
            )
        if matches:
            logger.info(
                "Found %d immediate matches for new keyword '%s'",
                len(matches),
                user_keyword.keyword,
            )
    except Exception:
        logger.exception("Immediate matching failed for keyword '%s'", user_keyword.keyword)

    return f"Aliases + embedding generated for keyword '{user_keyword.keyword}'"


@shared_task
def cleanup_old_data() -> str:
    """
    Daily cleanup task — removes old articles, ES documents, and sent records.

    Runs automatically at 2:00 AM via Celery Beat.

    Returns:
        Summary string.
    """
    logger.info("Starting daily cleanup …")
    stats: dict[str, int] = {}

    # Delete old NewsArticles (> 365 days)
    cutoff_articles = timezone.now() - timedelta(days=365)
    deleted_articles, _ = NewsArticle.objects.filter(scraped_at__lt=cutoff_articles).delete()
    stats['articles_deleted'] = deleted_articles
    logger.info("Deleted %d articles older than 365 days", deleted_articles)

    # Clean ElasticSearch index
    try:
        from .services.elasticsearch_service import ElasticSearchService

        es_service = ElasticSearchService()
        if es_service.is_connected:
            es_deleted = es_service.delete_old_articles(days=365)
            stats['es_deleted'] = es_deleted
        else:
            stats['es_deleted'] = 0
    except Exception:
        logger.exception("ES cleanup failed (non-fatal)")
        stats['es_deleted'] = 0

    # Delete old SentArticle records (> 90 days)
    cutoff_sent = timezone.now() - timedelta(days=90)
    deleted_sent, _ = SentArticle.objects.filter(sent_at__lt=cutoff_sent).delete()
    stats['sent_deleted'] = deleted_sent
    logger.info("Deleted %d sent records older than 90 days", deleted_sent)

    summary = (
        f"Cleanup done: {stats['articles_deleted']} articles, "
        f"{stats['es_deleted']} ES docs, "
        f"{stats['sent_deleted']} sent records deleted"
    )
    logger.info(summary)
    return summary


# =============================================================================
# Helpers
# =============================================================================


def _parse_date(date_str: str | None) -> Any:
    """
    Attempt to parse a date string into a timezone-aware datetime.

    Returns ``None`` if parsing fails.
    """
    if not date_str:
        return None

    from dateutil import parser as dateutil_parser

    try:
        dt = dateutil_parser.parse(date_str)
        if dt.tzinfo is None:
            from django.utils.timezone import make_aware
            dt = make_aware(dt)
        return dt
    except (ValueError, TypeError):
        logger.debug("Could not parse date: %s", date_str)
        return None



