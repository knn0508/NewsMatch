import requests
import logging
from django.conf import settings
from django.contrib.auth.models import User
from .models import UserProfile, Keyword

logger = logging.getLogger(__name__)


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
    
    def send_article_notification(self, chat_id, article, keyword):
        """Send article notification to user"""
        message = f"""
🔔 <b>New Article Match!</b>

📰 <b>Title:</b> {article.title}

🔑 <b>Keyword:</b> {keyword.keyword_name}

📅 <b>Date:</b> {article.date}

🔗 <b>Link:</b> {article.url}

📝 <b>Preview:</b>
{article.content[:300]}...
"""
        return self.send_message(chat_id, message)
    
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
        """Process incoming message"""
        chat_id = message['chat']['id']
        text = message.get('text', '')
        
        # Handle commands
        if text.startswith('/start'):
            return self.handle_start(chat_id, message)
        elif text.startswith('/help'):
            return self.handle_help(chat_id)
        elif text.startswith('/addkeyword'):
            return self.handle_add_keyword(chat_id, text, message)
        elif text.startswith('/removekeyword'):
            return self.handle_remove_keyword(chat_id, text, message)
        elif text.startswith('/mykeywords'):
            return self.handle_list_keywords(chat_id, message)
        elif text.startswith('/register'):
            return self.handle_register(chat_id, message)
        else:
            return self.send_message(
                chat_id, 
                "❓ Unknown command. Use /help to see available commands."
            )
    
    def handle_start(self, chat_id, message):
        """Handle /start command"""
        telegram_username = message['chat'].get('username')
        first_name = message['chat'].get('first_name', 'User')
        
        if not telegram_username:
            error_message = f"""
❌ <b>No Telegram Username Detected!</b>

Hello {first_name}, you need to set a Telegram username to use this bot.

<b>How to set a Telegram username:</b>
1. Open Telegram Settings
2. Tap on your profile
3. Edit "Username" field
4. Set a unique username (e.g., @john_doe)
5. Save and come back here

Once you have a username, send /start again!
"""
            return self.send_message(chat_id, error_message)
        
        welcome_message = f"""
👋 <b>Welcome to Media Trends Bot, @{telegram_username}!</b>

This bot helps you track news articles based on your keywords and sends instant notifications when matching articles are found.

<b>📋 Available Commands:</b>

/register - Register your account with your Telegram username
/addkeyword - Add a keyword to track (e.g., /addkeyword technology)
/removekeyword - Remove a keyword (e.g., /removekeyword technology)
/mykeywords - View all your tracked keywords
/help - Show detailed help

<b>🚀 Quick Start:</b>
1. Send /register to link your account
2. Send /addkeyword YOUR_TOPIC to start tracking
3. Get instant notifications when articles match! 🔔

Let's get started! Send /register now.
"""
        return self.send_message(chat_id, welcome_message)
    
    def handle_help(self, chat_id):
        """Handle /help command"""
        help_message = """
📚 <b>Media Trends Bot - Help Guide</b>

<b>Available Commands:</b>

🔹 /start - Start the bot and see welcome message
🔹 /help - Show this help message
🔹 /register - Register with your Telegram username
🔹 /addkeyword KEYWORD - Add a keyword to track
🔹 /removekeyword KEYWORD - Remove a keyword
🔹 /mykeywords - Show your tracked keywords

<b>📖 How It Works:</b>

1. <b>Register:</b> Link your Telegram account
   Command: /register
   
2. <b>Add Keywords:</b> Choose topics to track
   Examples:
   • /addkeyword technology
   • /addkeyword artificial intelligence
   • /addkeyword politics
   
3. <b>Get Notifications:</b> We'll send you articles that match your keywords automatically! 🔔

4. <b>Manage Keywords:</b>
   • View: /mykeywords
   • Remove: /removekeyword technology

<b>💡 Tips:</b>
• You can track multiple keywords
• Notifications are sent instantly when new articles are found
• Keywords are case-insensitive

Need help? Contact support or try /start to begin!
"""
        return self.send_message(chat_id, help_message)
    
    def handle_register(self, chat_id, message):
        """Handle /register command"""
        telegram_username = message['chat'].get('username')
        first_name = message['chat'].get('first_name', 'User')
        
        # Check if user has a Telegram username
        if not telegram_username:
            return self.send_message(
                chat_id,
                f"""❌ <b>Registration Failed</b>

Hello {first_name}, you need to set a Telegram username first!

<b>How to set a username:</b>
1. Open Telegram Settings ⚙️
2. Tap on your profile
3. Edit the "Username" field
4. Choose a unique username (e.g., john_doe)
5. Save changes

After setting your username, send /register again!"""
            )
        
        try:
            # Check if this chat_id is already registered
            existing_profile = UserProfile.objects.filter(telegram_chat_id=chat_id).first()
            if existing_profile:
                return self.send_message(
                    chat_id,
                    f"""ℹ️ <b>Already Registered</b>

You're already registered as <b>@{existing_profile.user.username}</b>!

You can now:
• Add keywords: /addkeyword TOPIC
• View keywords: /mykeywords
• Get help: /help"""
                )
            
            # Check if username already exists
            user = User.objects.filter(username=telegram_username).first()
            if not user:
                # Create new user with Telegram username
                user = User.objects.create_user(
                    username=telegram_username,
                    email=f"{telegram_username}@telegram.user"
                )
            
            # Create profile
            profile = UserProfile.objects.create(
                user=user,
                telegram_chat_id=chat_id
            )
            
            return self.send_message(
                chat_id,
                f"""✅ <b>Registration Successful!</b>

Welcome <b>@{telegram_username}</b>! Your account is now active.

<b>Next Steps:</b>
1. Add your first keyword: /addkeyword technology
2. View your keywords: /mykeywords
3. Start receiving article notifications! 🔔

<i>Tip: You can add multiple keywords to track different topics.</i>"""
            )
        except Exception as e:
            logger.error(f"Error registering user: {e}")
            return self.send_message(
                chat_id,
                "❌ Registration failed. Please try again or contact support."
            )
    
    def handle_add_keyword(self, chat_id, text, message):
        """Handle /addkeyword command"""
        telegram_username = message['chat'].get('username')
        
        # Check if user has Telegram username
        if not telegram_username:
            return self.send_message(
                chat_id,
                "❌ You need to set a Telegram username first. Check /start for instructions."
            )
        
        parts = text.split(maxsplit=1)
        if len(parts) < 2:
            return self.send_message(
                chat_id,
                "❌ Please provide a keyword.\n\n<b>Usage:</b> /addkeyword KEYWORD\n\n<b>Examples:</b>\n• /addkeyword technology\n• /addkeyword climate change\n• /addkeyword sports"
            )
        
        keyword_text = parts[1].strip()
        
        try:
            # Get user profile
            profile = UserProfile.objects.filter(telegram_chat_id=chat_id).first()
            if not profile:
                return self.send_message(
                    chat_id,
                    "❌ Please register first using /register"
                )
            
            # Create keyword
            keyword, created = Keyword.objects.get_or_create(
                user=profile.user,
                keyword_name=keyword_text
            )
            
            if created:
                keyword_count = Keyword.objects.filter(user=profile.user).count()
                return self.send_message(
                    chat_id,
                    f"""✅ <b>Keyword Added!</b>

Keyword: <b>'{keyword_text}'</b>

You'll receive instant notifications when articles match this keyword! 🔔

<i>Total keywords: {keyword_count}</i>

Add more: /addkeyword TOPIC
View all: /mykeywords"""
                )
            else:
                return self.send_message(
                    chat_id,
                    f"ℹ️ Keyword <b>'{keyword_text}'</b> is already in your tracking list."
                )
        except Exception as e:
            logger.error(f"Error adding keyword: {e}")
            return self.send_message(
                chat_id,
                "❌ Failed to add keyword. Please try again."
            )
    
    def handle_remove_keyword(self, chat_id, text, message):
        """Handle /removekeyword command"""
        telegram_username = message['chat'].get('username')
        
        # Check if user has Telegram username
        if not telegram_username:
            return self.send_message(
                chat_id,
                "❌ You need to set a Telegram username first. Check /start for instructions."
            )
        
        parts = text.split(maxsplit=1)
        if len(parts) < 2:
            return self.send_message(
                chat_id,
                "❌ Please provide a keyword.\n\n<b>Usage:</b> /removekeyword KEYWORD\n\n<b>Example:</b> /removekeyword technology"
            )
        
        keyword_text = parts[1].strip()
        
        try:
            # Get user profile
            profile = UserProfile.objects.filter(telegram_chat_id=chat_id).first()
            if not profile:
                return self.send_message(
                    chat_id,
                    "❌ Please register first using /register"
                )
            
            # Remove keyword
            deleted_count = Keyword.objects.filter(
                user=profile.user,
                keyword_name=keyword_text
            ).delete()[0]
            
            if deleted_count > 0:
                keyword_count = Keyword.objects.filter(user=profile.user).count()
                return self.send_message(
                    chat_id,
                    f"""✅ <b>Keyword Removed!</b>

Removed: <b>'{keyword_text}'</b>

You won't receive notifications for this keyword anymore.

<i>Remaining keywords: {keyword_count}</i>

View all: /mykeywords"""
                )
            else:
                return self.send_message(
                    chat_id,
                    f"❌ Keyword <b>'{keyword_text}'</b> not found in your list.\n\nUse /mykeywords to see your current keywords."
                )
        except Exception as e:
            logger.error(f"Error removing keyword: {e}")
            return self.send_message(
                chat_id,
                "❌ Failed to remove keyword. Please try again."
            )
    
    def handle_list_keywords(self, chat_id, message):
        """Handle /mykeywords command"""
        telegram_username = message['chat'].get('username')
        
        # Check if user has Telegram username
        if not telegram_username:
            return self.send_message(
                chat_id,
                "❌ You need to set a Telegram username first. Check /start for instructions."
            )
        
        try:
            # Get user profile
            profile = UserProfile.objects.filter(telegram_chat_id=chat_id).first()
            if not profile:
                return self.send_message(
                    chat_id,
                    "❌ Please register first using /register"
                )
            
            # Get keywords
            keywords = Keyword.objects.filter(user=profile.user)
            
            if keywords.exists():
                keyword_list = "\n".join([f"  {i+1}. {kw.keyword_name}" for i, kw in enumerate(keywords)])
                message = f"""📋 <b>Your Tracked Keywords</b>

{keyword_list}

<i>📊 Total: {keywords.count()} keyword(s)</i>

<b>Actions:</b>
• Add keyword: /addkeyword TOPIC
• Remove keyword: /removekeyword TOPIC"""
            else:
                message = """📋 <b>Your Keywords</b>

You haven't added any keywords yet.

<b>Get started:</b>
Add your first keyword to start tracking articles!

Example: /addkeyword technology

You can track multiple topics like politics, sports, business, etc."""
            
            return self.send_message(chat_id, message)
        except Exception as e:
            logger.error(f"Error listing keywords: {e}")
            return self.send_message(
                chat_id,
                "❌ Failed to retrieve keywords. Please try again."
            )
    
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


# Helper function to send notification
def send_telegram_notification(user, article, keyword):
    """Send article notification via Telegram"""
    try:
        profile = UserProfile.objects.filter(user=user).first()
        if profile and profile.telegram_chat_id:
            bot = TelegramBot()
            return bot.send_article_notification(profile.telegram_chat_id, article, keyword)
    except Exception as e:
        logger.error(f"Error sending Telegram notification: {e}")
    return None
