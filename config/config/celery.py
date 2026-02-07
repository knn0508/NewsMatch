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

# Periodic tasklar
app.conf.beat_schedule = {
    'scrape-azernews-every-1-minute': {
        'task': 'scraper.tasks.scrape_azernews',
        'schedule': crontab(minute='*/1'),
    },
    'scrape-apa-every-1-minute': {
        'task': 'scraper.tasks.scrape_apa',
        'schedule': crontab(minute='*/1'),
    },
    'scrape-azertag-every-1-minute': {
        'task': 'scraper.tasks.scrape_azertag',
        'schedule': crontab(minute='*/1'),
    },
}
