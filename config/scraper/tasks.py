from celery import shared_task
from .models import Article, Keyword, KeywordArticleMatch, Notification


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
    keywords = Keyword.objects.select_related('user').all()
    # Only check articles that haven't been matched yet for each keyword
    for kw in keywords:
        search_term = kw.keyword_name.lower()
        # Get articles not yet matched to this keyword
        already_matched_ids = KeywordArticleMatch.objects.filter(
            keyword=kw
        ).values_list('article_id', flat=True)

        new_articles = Article.objects.exclude(id__in=already_matched_ids).filter(
            models_q_title_or_content(search_term)
        )

        for article in new_articles:
            # Create the match
            KeywordArticleMatch.objects.get_or_create(
                keyword=kw,
                article=article,
            )
            # Create notification for the user
            Notification.objects.get_or_create(
                user=kw.user,
                keyword=kw,
                article=article,
            )

    return "Keyword matching completed"


def models_q_title_or_content(search_term):
    """Return a Q object that matches title OR content (case-insensitive)."""
    from django.db.models import Q
    return Q(title__icontains=search_term) | Q(content__icontains=search_term)



