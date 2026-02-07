from django.core.management.base import BaseCommand
from scraper.tasks import scrape_azernews, scrape_apa, scrape_azertag


class Command(BaseCommand):
    help = 'Test scraping all news sources'

    def add_arguments(self, parser):
        parser.add_argument(
            '--source',
            type=str,
            help='Specific source to scrape (azernews, apa, azertag)',
            default='all'
        )

    def handle(self, *args, **options):
        source = options['source']
        
        if source == 'all':
            self.stdout.write(self.style.WARNING('Scraping all sources...'))
            
            self.stdout.write('1. Scraping Azernews...')
            result1 = scrape_azernews()
            self.stdout.write(self.style.SUCCESS(f'   ✓ {result1}'))
            
            self.stdout.write('2. Scraping APA...')
            result2 = scrape_apa()
            self.stdout.write(self.style.SUCCESS(f'   ✓ {result2}'))
            
            self.stdout.write('3. Scraping Azertag...')
            result3 = scrape_azertag()
            self.stdout.write(self.style.SUCCESS(f'   ✓ {result3}'))
            
            self.stdout.write(self.style.SUCCESS('\n✓ All sources scraped!'))
        elif source == 'azernews':
            result = scrape_azernews()
            self.stdout.write(self.style.SUCCESS(f'✓ {result}'))
        elif source == 'apa':
            result = scrape_apa()
            self.stdout.write(self.style.SUCCESS(f'✓ {result}'))
        elif source == 'azertag':
            result = scrape_azertag()
            self.stdout.write(self.style.SUCCESS(f'✓ {result}'))
        else:
            self.stdout.write(self.style.ERROR(f'Unknown source: {source}'))
            self.stdout.write('Available sources: azernews, apa, azertag, all')
