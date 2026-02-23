# NewsMatch

Autonomous news monitoring system for Azerbaijani media. Scrapes news websites, matches articles to user-defined keywords using AI-powered text search with multilingual translations, and delivers notifications via Telegram.

## Architecture

```
┌─────────────┐     ┌──────────────┐     ┌──────────────────┐
│  Celery Beat │────▶│ Celery Worker │────▶│  Jina AI Reader  │
│  (scheduler) │     │  (tasks.py)  │     │  (free scraping)  │
└─────────────┘     └──────┬───────┘     └──────────────────┘
                           │
              ┌────────────┼────────────┐
              ▼            ▼            ▼
        ┌──────────┐ ┌──────────┐ ┌──────────┐
        │ SQLite   │ │  Elastic │ │ Telegram │
        │ (Django) │ │  Search  │ │ Bot API  │
        └──────────┘ └──────────┘ └──────────┘
```

### Pipeline (4 independent tasks)

| # | Task | Schedule | Purpose |
|---|------|----------|---------|
| 1 | `scrape_all_active_sources` | Every 5 min | Scrapes news homepages via Jina AI, saves new articles to DB |
| 2 | `generate_article_embeddings` | Every 5 min (offset +1) | Generates 768-dim embeddings for new articles, indexes in ElasticSearch |
| 3 | `match_and_notify_users` | Every 5 min (offset +2) | Matches articles to user keywords, sends Telegram notifications |
| 4 | `cleanup_old_data` | Daily at 2:00 AM | Removes articles >365 days, sent records >90 days |

## Key Components

### Scraping — Jina AI Reader (`scraper/services/jina_scraper.py`)
- Uses [Jina AI Reader](https://r.jina.ai/) (free, no API key required for basic usage)
- No manual CSS selectors — adapts to any website automatically
- Extracts article title, content, description, author, publish date, and category
- Filters out boilerplate descriptions, footer text, navigation links, and related-article sidebars

### Keyword Matching (`scraper/services/news_matcher.py`)
- **Pure text search** with whole-word matching (no false partial matches: "şəki" ≠ "şəkil")
- **Multilingual aliases** via `deep-translator` — when a user adds "Azerbaijan", the system auto-translates to `Azərbaycan`, `Azerbaycan`, `Азербайджан`, `أذربيجان`, etc.
- Filters out nav/sidebar/footer junk to prevent false positives
- Two-tier matching: title/description (score 1.0) → content sentences (score 0.95)

### Embeddings (`scraper/services/embedding_service.py`)
- Uses `paraphrase-multilingual-mpnet-base-v2` (768-dim, free, open-source)
- Singleton pattern for efficient model reuse
- Batch processing support

### ElasticSearch (`scraper/services/elasticsearch_service.py`)
- Dense vector indexing with cosine similarity
- Article indexing and cleanup
- Graceful degradation — system works without ES

### Telegram Bot (`scraper/telegram_bot.py`)
- Commands: `/start`, `/help`, `/add_keyword`, `/remove_keyword`, `/my_keywords`, `/latest_news`
- Long-polling based (no webhooks needed)
- Keyword aliases generated automatically on subscription
- Telegram bot link: https://t.me/News_NotifierBot

## Project Structure

```
config/                          # Django project root
├── config/                      # Django settings & configuration
│   ├── settings.py              # All settings (Django, Celery, Jina, ES, Telegram)
│   ├── celery.py                # Celery Beat schedule (4 periodic tasks)
│   ├── urls.py                  # Admin URLs
│   └── wsgi.py / asgi.py        # WSGI/ASGI entry points
├── scraper/                     # Main Django app
│   ├── models.py                # NewsSource, NewsArticle, UserKeyword, SentArticle
│   ├── admin.py                 # Django admin with scrape/reindex actions
│   ├── tasks.py                 # Celery tasks (scrape, embed, match, cleanup)
│   ├── telegram_bot.py          # Telegram bot command handlers
│   ├── services/                # Business logic services
│   │   ├── jina_scraper.py      # Jina AI web scraping
│   │   ├── elasticsearch_service.py  # ES indexing & maintenance
│   │   ├── embedding_service.py # Sentence-transformer embeddings
│   │   ├── langchain_processor.py    # Text processing & chunking
│   │   ├── news_matcher.py      # Keyword-article matching
│   │   └── translation_service.py    # Multilingual keyword translation
│   └── management/commands/     # Django management commands
│       ├── init_elasticsearch.py     # Create ES index
│       ├── reindex_elasticsearch.py  # Re-index all articles in ES
│       ├── backfill_embeddings.py    # Generate missing embeddings
│       ├── check_keywords.py         # Test keyword matching
│       ├── test_scrape.py            # Test scrape a source
│       └── run_telegram_bot.py       # Start the Telegram bot
├── manage.py
├── requirements.txt
└── db.sqlite3
```

## Setup

### Prerequisites

- Python 3.11+
- Redis (for Celery broker)
- ElasticSearch 8.x (optional — system works without it)
- Telegram Bot Token (from [@BotFather](https://t.me/BotFather))

### Installation

```bash
cd config
pip install -r requirements.txt
python manage.py migrate
```

### Configuration

All settings are in `config/settings.py`:

| Setting | Default | Description |
|---------|---------|-------------|
| `TG_BOT_TOKEN` | env `TELEGRAM_BOT_TOKEN` | Telegram bot token |
| `JINA_API_KEY` | `""` (optional) | Jina AI API key for higher rate limits |
| `ELASTICSEARCH_HOST` | `http://localhost:9200` | ElasticSearch URL |
| `EMBEDDING_MODEL` | `paraphrase-multilingual-mpnet-base-v2` | Sentence-transformer model |
| `SCRAPE_TIMEOUT` | `30` | HTTP timeout for scraping (seconds) |
| `MAX_ARTICLES_PER_SCRAPE` | `20` | Max articles per source per run |
| `SEMANTIC_TITLE_THRESHOLD` | `0.45` | Semantic matching threshold |

### Running

**1. Initialize ElasticSearch (optional):**
```bash
python manage.py init_elasticsearch
```

**2. Add news sources via Django Admin:**
```bash
python manage.py createsuperuser
python manage.py runserver
# Visit http://localhost:8000/admin/scraper/newssource/add/
```

**3. Start the Celery worker:**
```bash
celery -A config worker -l info --pool=solo
```

**4. Start the Celery Beat scheduler:**
```bash
celery -A config beat -l info
```

**5. Start the Telegram bot:**
```bash
python manage.py run_telegram_bot
```

### Management Commands

```bash
# Test scraping a specific source
python manage.py test_scrape --source "Sia.az" --sync

# Test scraping all active sources
python manage.py test_scrape --sync

# Re-index all articles in ElasticSearch
python manage.py reindex_elasticsearch

# Backfill missing embeddings
python manage.py backfill_embeddings

# Check keyword matches
python manage.py check_keywords
```

## Adding a News Source

1. Go to Django Admin → News Sources → Add
2. Enter the source name and homepage URL (e.g. `https://sia.az`)
3. Set `Active = True` and `Scrape Interval (hours) = 1`
4. Save — the system will automatically scrape it on the next Celery Beat cycle

No CSS selectors or custom code needed. Jina AI handles content extraction automatically.

## Tech Stack

| Component | Technology | Cost |
|-----------|-----------|------|
| Web Scraping | Jina AI Reader | Free (1M tokens/month) |
| Embeddings | sentence-transformers | Free (open-source, runs locally) |
| Text Matching | Regex whole-word search + translated aliases | Free |
| Translation | deep-translator (Google Translate) | Free |
| Task Queue | Celery + Redis | Free (self-hosted) |
| Search Index | ElasticSearch 8.x | Free (self-hosted, optional) |
| Notifications | Telegram Bot API | Free |
| Database | SQLite (Django) | Free |
| Framework | Django 5+ | Free |

## Setup Instructions

### Telegram Bot API Key
To enable Telegram notifications, developers must add their Telegram Bot API key in the appropriate configuration file. Replace the placeholder `<TELEGRAM_BOT_TOKEN>` with your actual API key in the `TelegramBot` class located in `scraper/telegram_bot.py`. This is required for the bot to function correctly.
