# Telegram Bot Setup Guide

## Overview
This project now includes a Telegram bot that allows users to manage their article keywords and receive real-time notifications when articles matching their keywords are found.

## Features
- User registration via Telegram
- Add/remove keywords through bot commands
- Automatic article notifications via Telegram
- List all user keywords

## Setup Instructions

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

### 2. Configure Database
The project uses SQLite by default. Make sure to run migrations:

```bash
cd config
python manage.py makemigrations
python manage.py migrate
```

### 3. Start Required Services

#### Start Redis (for Celery)
```bash
redis-server
```

#### Start Celery Worker
```bash
cd config
celery -A config worker --loglevel=info
```

#### Start Celery Beat (for periodic tasks)
```bash
cd config
celery -A config beat --loglevel=info
```

#### Start Telegram Bot
```bash
cd config
python manage.py run_telegram_bot
```

## Telegram Bot Commands

### User Commands (to be used in Telegram):

1. **`/start`** - Start the bot and see welcome message
2. **`/help`** - Display available commands
3. **`/register USERNAME`** - Register your account
   - Example: `/register john_doe`
4. **`/addkeyword KEYWORD`** - Add a keyword to track
   - Example: `/addkeyword technology`
   - Example: `/addkeyword artificial intelligence`
5. **`/removekeyword KEYWORD`** - Remove a keyword
   - Example: `/removekeyword technology`
6. **`/mykeywords`** - List all your keywords

## Workflow

### For Users:
1. Open Telegram and find your bot by username
2. Send `/start` to begin
3. Register: `/register your_username`
4. Add keywords: `/addkeyword technology`
5. Wait for article notifications!

### Automatic Process:
1. Celery tasks scrape articles periodically
2. System matches articles with user keywords
3. When a match is found:
   - Creates a notification in database
   - Sends Telegram message to user with article details

## Bot Token Configuration

Your bot token is already configured in `config/settings.py`:
```python
TG_BOT_TOKEN = "8328248487:AAFyQYtSUnEuKam2QZXTVBoDur7HnfxxGAY"
```

## Architecture

### Models:
- **UserProfile** - Stores Telegram chat_id for each user
- **Keyword** - User keywords for tracking
- **Article** - Scraped articles
- **KeywordArticleMatch** - Matches between keywords and articles
- **Notification** - Notification records

### Key Files:
- `scraper/telegram_bot.py` - Main bot logic
- `scraper/tasks.py` - Celery tasks with Telegram integration
- `scraper/management/commands/run_telegram_bot.py` - Management command to run bot
- `scraper/models.py` - Database models

## Testing

1. Register a test user:
   ```
   /register testuser
   ```

2. Add a test keyword:
   ```
   /addkeyword politics
   ```

3. Run a scraping task manually:
   ```bash
   cd config
   python manage.py shell
   >>> from scraper.tasks import scrape_azernews, match_keywords_to_articles
   >>> scrape_azernews()
   >>> match_keywords_to_articles()
   ```

4. Check if notification was sent to Telegram

## Troubleshooting

- **Bot not responding**: Make sure `run_telegram_bot` command is running
- **No notifications**: Check that Celery worker and beat are running
- **Registration fails**: Verify username is correct and not already taken
- **Redis connection error**: Ensure Redis server is running

## Production Deployment

For production:
1. Use environment variables for sensitive data (bot token)
2. Use PostgreSQL instead of SQLite
3. Run services with supervisord or systemd
4. Set up proper logging
5. Use webhook instead of polling for better performance
