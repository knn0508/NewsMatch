"""
Celery configuration for the MEDIATRENDS project.

Beat schedule:
- AI-powered autonomous scraping (hourly via Jina AI)
- Daily cleanup of old data
"""

import os
import platform
from celery import Celery
from celery.schedules import crontab

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

app = Celery('config')
app.config_from_object('django.conf:settings', namespace='CELERY')
app.autodiscover_tasks()

# Use 'solo' pool on Windows (prefork/billiard doesn't work on Windows)
if platform.system() == 'Windows':
    app.conf.worker_pool = 'solo'

# --------------------------------------------------------------------------
# Periodic tasks — each runs INDEPENDENTLY so they don't block each other.
# Staggered schedules prevent overlap on the solo pool (Windows).
# --------------------------------------------------------------------------
app.conf.beat_schedule = {
    # ── TASK 1: Scrape news sources ──────────────────────────────────────
    # Only scrapes & saves articles to DB. No embedding / matching here.
    'scrape-all-sources': {
        'task': 'scraper.tasks.scrape_all_active_sources',
        'schedule': crontab(minute='*/5'),  # Every 5 minutes
    },

    # ── TASK 2: Generate embeddings for new articles ─────────────────────
    # Picks up articles without embeddings, generates them + ES index.
    'generate-embeddings': {
        'task': 'scraper.tasks.generate_article_embeddings',
        'schedule': crontab(minute='1-59/5'),  # Every 5 min, offset by 1 min
    },

    # ── TASK 3: Match articles to keywords & send notifications ──────────
    # Finds embedded articles, matches user keywords, sends Telegram msgs.
    'match-and-notify': {
        'task': 'scraper.tasks.match_and_notify_users',
        'schedule': crontab(minute='2-59/5'),  # Every 5 min, offset by 2 min
    },

    # ── TASK 4: Daily cleanup of old articles and sent records ───────────
    'cleanup-old-data-daily': {
        'task': 'scraper.tasks.cleanup_old_data',
        'schedule': crontab(hour=2, minute=0),  # Daily at 2:00 AM
    },
}
