"""
Telegram bot for MEDIATRENDS — handles user commands and notifications.

All keyword matching is AI-powered using semantic embeddings (sentence-transformers).
No legacy BeautifulSoup scraping — everything is scraped via Jina AI.

Commands:
    /start                    — Welcome message
    /help                     — Help guide
    /add_keyword <keyword>    — Subscribe to a topic with semantic matching
    /remove_keyword <keyword> — Unsubscribe from a topic
    /my_keywords              — List all semantic keyword subscriptions
    /latest_news              — Show recent matched articles (last 24h)
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

import requests
from django.conf import settings
from django.utils import timezone

from .models import UserKeyword, SentArticle

logger = logging.getLogger('scraper')


class TelegramBot:
    def __init__(self):
        self.token = settings.TG_BOT_TOKEN
        self.base_url = f"https://api.telegram.org/bot{self.token}"
        
    def send_message(self, chat_id, text, parse_mode='HTML'):
        """Send a message to a Telegram user"""
        url = f"{self.base_url}/sendMessage"
        data = {
            'chat_id': chat_id,
            'text': text,
            'parse_mode': parse_mode,
        }
        try:
            response = requests.post(url, json=data, timeout=10)
            return response.json()
        except Exception as e:
            logger.error(f"Error sending message to {chat_id}: {e}")
            return None
    
    def get_updates(self, offset=None):
        """Get updates from Telegram"""
        url = f"{self.base_url}/getUpdates"
        params = {'timeout': 30}
        if offset:
            params['offset'] = offset
        
        try:
            response = requests.get(url, params=params, timeout=35)
            return response.json()
        except Exception as e:
            logger.error(f"Error getting updates: {e}")
            return None
    
    def process_message(self, message):
        """Process incoming message — dispatch to the appropriate handler."""
        chat_id = message['chat']['id']
        text = message.get('text', '')

        # Handle commands
        if text.startswith('/start'):
            return self.handle_start(chat_id, message)
        elif text.startswith('/help'):
            return self.handle_help(chat_id)
        elif text.startswith('/add_keyword'):
            return self.handle_add_semantic_keyword(chat_id, text, message)
        elif text.startswith('/remove_keyword'):
            return self.handle_remove_semantic_keyword(chat_id, text, message)
        elif text.startswith('/my_keywords'):
            return self.handle_list_semantic_keywords(chat_id, message)
        elif text.startswith('/latest_news'):
            return self.handle_latest_news(chat_id, message)
        else:
            return self.send_message(
                chat_id,
                "❓ Unknown command. Use /help to see available commands."
            )
    
    def handle_start(self, chat_id, message):
        """Handle /start command"""
        first_name = message['chat'].get('first_name', 'User')
        
        welcome_message = f"""
👋 <b>Welcome to Media Trends Bot, {first_name}!</b>

This bot uses <b>AI-powered semantic matching</b> to track news articles and send you instant notifications when relevant articles are found.

<b>📋 Available Commands:</b>

/add_keyword - Add a keyword to track. We prefer use exact phrases for better matching (e.g., /add_keyword Baku city)
/remove_keyword - Remove a keyword (e.g., /remove_keyword Baku city)
/my_keywords - View all your tracked keywords
/latest_news - Show recent matched articles (last 24h)
/help - Show detailed help

<b>🚀 Quick Start:</b>
1. Send /add_keyword YOUR_TOPIC to start tracking
2. Get instant notifications when articles match! 🔔

🧠 Semantic matching means the AI understands context — not just exact text matches!
"""
        return self.send_message(chat_id, welcome_message)
    
    def handle_help(self, chat_id):
        """Handle /help command"""
        help_message = """
📚 <b>Media Trends Bot - Help Guide</b>

<b>Available Commands:</b>

🔹 /start - Start the bot and see welcome message
🔹 /help - Show this help message
🔹 /add_keyword KEYWORD - Add a keyword to track. We prefer use exact phrases for better matching (e.g., /add_keyword Baku city)
🔹 /remove_keyword KEYWORD - Remove a keyword (e.g., /remove_keyword Baku city)
🔹 /my_keywords - Show your tracked keywords
🔹 /latest_news - Show recent matched articles (last 24h)

<b>📖 How It Works:</b>

1. <b>Add Keywords:</b> Choose topics to track
   Examples:
   • /add_keyword technology
   • /add_keyword artificial intelligence
   • /add_keyword neft qiyməti

2. <b>Get Notifications:</b> AI finds semantically relevant articles and notifies you automatically! 🔔

3. <b>Manage Keywords:</b>
   • View: /my_keywords
   • Remove: /remove_keyword technology

<b>🧠 AI-Powered Matching:</b>
Unlike simple text search, our system uses semantic embeddings.
This means /add_keyword Şəki will match articles <i>about</i> Şəki city
without false positives like 'şəkil' (picture).

<b>💡 Tips:</b>
• You can track multiple keywords
• Notifications are sent instantly when new articles are found
• News sources are scraped automatically every hour
"""
        return self.send_message(chat_id, help_message)
    
    def run_polling(self):
        """Run bot with long polling"""
        logger.info("Starting Telegram bot polling...")
        offset = None
        
        while True:
            try:
                updates = self.get_updates(offset)
                if updates and updates.get('ok'):
                    for update in updates.get('result', []):
                        offset = update['update_id'] + 1
                        if 'message' in update:
                            self.process_message(update['message'])
            except KeyboardInterrupt:
                logger.info("Bot stopped by user")
                break
            except Exception as e:
                logger.error(f"Error in polling loop: {e}")
                import time
                time.sleep(5)

    # ==================================================================
    # NEW AI-powered semantic keyword handlers
    # ==================================================================

    def handle_add_semantic_keyword(self, chat_id: int, text: str, message: dict) -> Any:
        """
        Handle /add_keyword <keyword> — subscribe with semantic matching.

        Creates a ``UserKeyword`` and dispatches embedding generation.
        """
        parts = text.split(maxsplit=1)
        if len(parts) < 2:
            return self.send_message(
                chat_id,
                "❌ Please provide a keyword.\n\n"
                "<b>Usage:</b> /add_keyword KEYWORD\n\n"
                "<b>Examples:</b>\n"
                "• /add_keyword Şəki\n"
                "• /add_keyword climate change\n"
                "• /add_keyword neft qiyməti",
            )

        keyword_text = parts[1].strip()
        user_id = message['from']['id']

        try:
            keyword, created = UserKeyword.objects.get_or_create(
                user_id=user_id,
                keyword=keyword_text,
            )

            if created:
                # Dispatch alias generation + embedding asynchronously
                from .tasks import generate_keyword_embedding
                generate_keyword_embedding.delay(keyword.id)

                count = UserKeyword.objects.filter(user_id=user_id).count()
                return self.send_message(
                    chat_id,
                    f"✅ <b>Keyword Added!</b>\n\n"
                    f"Keyword: <b>'{keyword_text}'</b>\n\n"
                    f"🌐 Generating translations (EN, AZ, TR, RU, AR, FR, DE)...\n"
                    f"The system will match articles in <i>any</i> of these languages!\n\n"
                    f"<i>Total keywords: {count}</i>\n\n"
                    f"Add more: /add_keyword TOPIC\n"
                    f"View all: /my_keywords",
                )
            else:
                return self.send_message(
                    chat_id,
                    f"ℹ️ Keyword <b>'{keyword_text}'</b> is already in your semantic tracking list.",
                )
        except Exception as e:
            logger.error(f"Error adding semantic keyword: {e}")
            return self.send_message(chat_id, "❌ Failed to add keyword. Please try again.")

    def handle_remove_semantic_keyword(self, chat_id: int, text: str, message: dict) -> Any:
        """Handle /remove_keyword <keyword> — remove semantic subscription."""
        parts = text.split(maxsplit=1)
        if len(parts) < 2:
            return self.send_message(
                chat_id,
                "❌ Please provide a keyword.\n\n"
                "<b>Usage:</b> /remove_keyword KEYWORD\n\n"
                "<b>Example:</b> /remove_keyword Şəki",
            )

        keyword_text = parts[1].strip()
        user_id = message['from']['id']

        try:
            deleted_count, _ = UserKeyword.objects.filter(
                user_id=user_id,
                keyword=keyword_text,
            ).delete()

            if deleted_count > 0:
                remaining = UserKeyword.objects.filter(user_id=user_id).count()
                return self.send_message(
                    chat_id,
                    f"✅ <b>Keyword Removed!</b>\n\n"
                    f"Removed: <b>'{keyword_text}'</b>\n\n"
                    f"You won't receive semantic matches for this keyword anymore.\n\n"
                    f"<i>Remaining keywords: {remaining}</i>",
                )
            else:
                return self.send_message(
                    chat_id,
                    f"❌ Keyword <b>'{keyword_text}'</b> not found.\n\n"
                    f"Use /my_keywords to see your current keywords.",
                )
        except Exception as e:
            logger.error(f"Error removing semantic keyword: {e}")
            return self.send_message(chat_id, "❌ Failed to remove keyword. Please try again.")

    def handle_list_semantic_keywords(self, chat_id: int, message: dict) -> Any:
        """Handle /my_keywords — list all semantic keyword subscriptions."""
        user_id = message['from']['id']

        try:
            keywords = UserKeyword.objects.filter(user_id=user_id).order_by('keyword')

            if keywords.exists():
                lines: list[str] = []
                for i, kw in enumerate(keywords, 1):
                    alias_count = len(kw.keyword_aliases) if kw.keyword_aliases else 0
                    status = f"🌐 {alias_count} langs" if alias_count > 0 else "⏳ translating"
                    lines.append(f"  {i}. {kw.keyword} ({status})")

                keyword_list = "\n".join(lines)
                msg = (
                    f"📋 <b>Your Keywords</b>\n\n"
                    f"{keyword_list}\n\n"
                    f"🌐 = translations ready | ⏳ = processing\n\n"
                    f"<i>📊 Total: {keywords.count()} keyword(s)</i>\n\n"
                    f"<b>Actions:</b>\n"
                    f"• Add keyword: /add_keyword TOPIC\n"
                    f"• Remove keyword: /remove_keyword TOPIC\n"
                    f"• Recent news: /latest_news"
                )
            else:
                msg = (
                    "📋 <b>Your Semantic Keywords</b>\n\n"
                    "You haven't added any semantic keywords yet.\n\n"
                    "<b>Get started:</b>\n"
                    "/add_keyword Şəki\n"
                    "/add_keyword neft qiyməti\n\n"
                    "🧠 Semantic matching uses AI to find <i>relevant</i> news, "
                    "not just exact text matches!"
                )

            return self.send_message(chat_id, msg)
        except Exception as e:
            logger.error(f"Error listing semantic keywords: {e}")
            return self.send_message(chat_id, "❌ Failed to retrieve keywords. Please try again.")

    def handle_latest_news(self, chat_id: int, message: dict) -> Any:
        """Handle /latest_news — show recent matched articles (last 24h)."""
        user_id = message['from']['id']

        try:
            cutoff = timezone.now() - timedelta(hours=24)
            recent_sent = (
                SentArticle.objects
                .filter(user_id=user_id, sent_at__gte=cutoff)
                .select_related('article', 'article__source')
                .order_by('-sent_at')[:10]
            )

            if recent_sent:
                lines: list[str] = []
                for i, sa in enumerate(recent_sent, 1):
                    score_pct = f"{sa.similarity_score:.0%}" if sa.similarity_score else "N/A"
                    title = sa.article.title[:80] if sa.article else "Unknown"
                    url = sa.article.url if sa.article else ""
                    kw = sa.matched_keyword or "—"
                    lines.append(
                        f"{i}. <a href=\"{url}\">{title}</a>\n"
                        f"   🔑 {kw} | 📊 {score_pct}"
                    )

                articles_text = "\n\n".join(lines)
                msg = (
                    f"📰 <b>Your Latest News (last 24h)</b>\n\n"
                    f"{articles_text}\n\n"
                    f"<i>Showing {len(recent_sent)} most recent matches</i>"
                )
            else:
                msg = (
                    "📰 <b>Your Latest News</b>\n\n"
                    "No articles matched in the last 24 hours.\n\n"
                    "Make sure you have keywords set up: /my_keywords"
                )

            return self.send_message(chat_id, msg)
        except Exception as e:
            logger.error(f"Error fetching latest news: {e}")
            return self.send_message(chat_id, "❌ Failed to fetch recent news. Please try again.")
