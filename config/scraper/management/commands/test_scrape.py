from django.core.management.base import BaseCommand
from scraper.models import NewsSource
from scraper.tasks import scrape_single_source


class Command(BaseCommand):
    help = 'Test scraping news sources via Jina AI'

    def add_arguments(self, parser):
        parser.add_argument(
            '--source',
            type=str,
            help='Name or ID of a specific source to scrape (or "all" for all active)',
            default='all'
        )
        parser.add_argument(
            '--sync',
            action='store_true',
            help='Run synchronously (not via Celery)',
        )

    def handle(self, *args, **options):
        source_arg = options['source']
        sync = options['sync']

        if source_arg == 'all':
            sources = NewsSource.objects.filter(is_active=True)
            if not sources.exists():
                self.stdout.write(self.style.WARNING(
                    'No active news sources. Add one in Django admin: /admin/scraper/newssource/add/'
                ))
                return

            self.stdout.write(self.style.WARNING(
                f'Scraping {sources.count()} active source(s) via Jina AI...'
            ))

            for i, source in enumerate(sources, 1):
                self.stdout.write(f'{i}. {source.name} ({source.url})')
                if sync:
                    result = scrape_single_source(source.id)
                    self.stdout.write(self.style.SUCCESS(f'   ✓ {result}'))
                else:
                    scrape_single_source.delay(source.id)
                    self.stdout.write(self.style.SUCCESS(f'   ✓ Task dispatched'))

            self.stdout.write(self.style.SUCCESS('\n✓ All sources processed!'))
        else:
            # Try to find source by name or ID
            try:
                source = NewsSource.objects.get(id=int(source_arg))
            except (ValueError, NewsSource.DoesNotExist):
                source = NewsSource.objects.filter(name__icontains=source_arg).first()

            if not source:
                self.stdout.write(self.style.ERROR(f'Source not found: {source_arg}'))
                self.stdout.write('Available sources:')
                for s in NewsSource.objects.all():
                    status = '✓' if s.is_active else '✗'
                    self.stdout.write(f'  [{status}] {s.id}: {s.name} ({s.url})')
                return

            self.stdout.write(f'Scraping: {source.name} ({source.url})')
            if sync:
                result = scrape_single_source(source.id)
                self.stdout.write(self.style.SUCCESS(f'✓ {result}'))
            else:
                scrape_single_source.delay(source.id)
                self.stdout.write(self.style.SUCCESS('✓ Task dispatched'))
