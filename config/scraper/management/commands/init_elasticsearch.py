"""
Management command: Initialize ElasticSearch index.

Creates the ``news_articles`` index with the correct mapping for
dense-vector (768-dim) search.

Usage:
    python manage.py init_elasticsearch
    python manage.py init_elasticsearch --delete-existing
"""

from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = 'Initialize the ElasticSearch index for news articles with vector mapping.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--delete-existing',
            action='store_true',
            default=False,
            help='Delete and recreate the index if it already exists.',
        )

    def handle(self, *args, **options):
        delete_existing = options['delete_existing']

        self.stdout.write(self.style.NOTICE('Connecting to ElasticSearch …'))

        try:
            from scraper.services.elasticsearch_service import ElasticSearchService

            es = ElasticSearchService()

            if not es.is_connected:
                raise CommandError(
                    'Cannot connect to ElasticSearch. '
                    'Make sure it is running at the configured host.'
                )

            self.stdout.write(self.style.SUCCESS('✓ Connected to ElasticSearch'))

            if delete_existing:
                self.stdout.write(self.style.WARNING('Deleting existing index …'))

            success = es.create_index(delete_existing=delete_existing)

            if success:
                self.stdout.write(self.style.SUCCESS(
                    '✓ ElasticSearch index "news_articles" is ready.'
                ))
            else:
                raise CommandError('Failed to create ElasticSearch index.')

        except ImportError as exc:
            raise CommandError(f'Missing dependency: {exc}')
        except Exception as exc:
            raise CommandError(f'Error: {exc}')
