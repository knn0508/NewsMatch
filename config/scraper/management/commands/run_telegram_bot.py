from django.core.management.base import BaseCommand
from scraper.telegram_bot import TelegramBot


class Command(BaseCommand):
    help = 'Run the Telegram bot'

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS('Starting Telegram bot...'))
        bot = TelegramBot()
        try:
            bot.run_polling()
        except KeyboardInterrupt:
            self.stdout.write(self.style.SUCCESS('\nBot stopped successfully'))
