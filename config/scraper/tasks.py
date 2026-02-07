from celery import shared_task
from .models import Article, Keyword, KeywordArticleMatch, Notification
from .telegram_bot import send_telegram_notification
import logging

logger = logging.getLogger(__name__)


@shared_task
def scrape_azernews():
    """Azernews scrape edir"""
    from .sites.azernews_az import scrape_articles
    scrape_articles()
    match_keywords_to_articles()
    return "Azernews scrape edildi"


@shared_task
def scrape_apa():
    """APA RSS scrape edir"""
    from .sites.apa_az import scrape_articles
    scrape_articles()
    match_keywords_to_articles()
    return "APA scrape edildi"


@shared_task
def scrape_azertag():
    """Azertag scrape edir"""
    from .sites.azertag_az import scrape_articles
    scrape_articles()
    match_keywords_to_articles()
    return "Azertag scrape edildi"

@shared_task
def match_keywords_to_articles():
    """
    All keywords are checked against articles.
    If a keyword appears in the article title or content,
    a KeywordArticleMatch and Notification are created.
    """
    logger.info("Starting keyword matching for all keywords...")
    keywords = Keyword.objects.select_related('user').all()
    total_matches = 0
    
    if not keywords.exists():
        logger.info("No keywords found in database")
        return "No keywords to match"
    
    logger.info(f"Checking {keywords.count()} keywords against articles...")
    
    # Check ALL keywords every time
    for kw in keywords:
        search_term = kw.keyword_name.lower()
        # Get articles not yet matched to this keyword
        already_matched_ids = KeywordArticleMatch.objects.filter(
            keyword=kw
        ).values_list('article_id', flat=True)

        new_articles = Article.objects.exclude(id__in=already_matched_ids).filter(
            models_q_title_or_content(search_term)
        )

        if new_articles.exists():
            logger.info(f"Found {new_articles.count()} new articles for keyword '{kw.keyword_name}' (user: {kw.user.username})")

        for article in new_articles:
            # Create the match
            match, match_created = KeywordArticleMatch.objects.get_or_create(
                keyword=kw,
                article=article,
            )
            
            # Create notification for the user
            notification, notif_created = Notification.objects.get_or_create(
                user=kw.user,
                keyword=kw,
                article=article,
            )
            
            # Send Telegram notification immediately if new match
            if notif_created:
                logger.info(f"Sending Telegram notification to {kw.user.username} for article: {article.title[:50]}...")
                result = send_telegram_notification(kw.user, article, kw)
                if result:
                    logger.info(f"✓ Notification sent successfully to {kw.user.username}")
                    total_matches += 1
                else:
                    logger.warning(f"✗ Failed to send notification to {kw.user.username}")

    logger.info(f"Keyword matching completed. Total new notifications sent: {total_matches}")
    return f"Keyword matching completed. Sent {total_matches} notifications"


def models_q_title_or_content(search_term):
    """Return a Q object that matches title OR content (case-insensitive)."""
    from django.db.models import Q
    return Q(title__icontains=search_term) | Q(content__icontains=search_term)



