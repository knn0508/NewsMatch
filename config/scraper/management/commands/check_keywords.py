from django.core.management.base import BaseCommand
from scraper.tasks import match_keywords_to_articles


class Command(BaseCommand):
    help = 'Manually check all keywords and send notifications'

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS('Checking all keywords against articles...'))
        result = match_keywords_to_articles()
        self.stdout.write(self.style.SUCCESS(f'✓ {result}'))
