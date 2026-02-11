"""
Management command: Reindex all articles in ElasticSearch.

Reads every ``NewsArticle`` with an embedding and bulk-indexes them
into the ``news_articles`` ES index.

Usage:
    python manage.py reindex_elasticsearch
    python manage.py reindex_elasticsearch --batch-size 200
    python manage.py reindex_elasticsearch --recreate-index
"""

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone


class Command(BaseCommand):
    help = 'Reindex all news articles in ElasticSearch.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--batch-size',
            type=int,
            default=100,
            help='Number of articles per bulk-index call (default: 100).',
        )
        parser.add_argument(
            '--recreate-index',
            action='store_true',
            default=False,
            help='Delete and recreate the ES index before reindexing.',
        )

    def handle(self, *args, **options):
        batch_size = options['batch_size']
        recreate = options['recreate_index']

        try:
            from scraper.services.elasticsearch_service import ElasticSearchService

            es = ElasticSearchService()

            if not es.is_connected:
                raise CommandError(
                    'Cannot connect to ElasticSearch. '
                    'Make sure it is running at the configured host.'
                )

            self.stdout.write(self.style.SUCCESS('✓ Connected to ElasticSearch'))

            # Optionally recreate the index
            if recreate:
                self.stdout.write(self.style.WARNING('Recreating index …'))
                es.create_index(delete_existing=True)
                self.stdout.write(self.style.SUCCESS('✓ Index recreated'))

        except ImportError as exc:
            raise CommandError(f'Missing dependency: {exc}')

        from scraper.models import NewsArticle

        articles_qs = NewsArticle.objects.filter(
            content_embedding__isnull=False,
        ).select_related('source')
        total = articles_qs.count()

        if total == 0:
            self.stdout.write('No articles with embeddings to index.')
            return

        self.stdout.write(f'Reindexing {total} articles (batch_size={batch_size}) …')

        total_success = 0
        total_failed = 0

        for start in range(0, total, batch_size):
            batch = list(articles_qs[start:start + batch_size])
            es_docs = []

            for article in batch:
                es_docs.append({
                    'article_id': article.id,
                    'title': article.title,
                    'content': article.content[:10000],
                    'description': article.description,
                    'url': article.url,
                    'source': article.source.name if article.source else '',
                    'author': article.author,
                    'publish_date': article.publish_date.isoformat() if article.publish_date else None,
                    'scraped_at': article.scraped_at.isoformat() if article.scraped_at else None,
                    'content_embedding': article.content_embedding,
                })

            result = es.bulk_index_articles(es_docs)
            total_success += result.get('success', 0)
            total_failed += result.get('failed', 0)

            # Update DB flags
            article_ids = [a.id for a in batch]
            now = timezone.now()
            NewsArticle.objects.filter(id__in=article_ids).update(
                es_indexed=True,
                es_index_date=now,
            )

            self.stdout.write(
                f'  … {min(start + batch_size, total)}/{total} '
                f'(success={total_success}, failed={total_failed})'
            )

        self.stdout.write(self.style.SUCCESS(
            f'\n✓ Reindexing complete: {total_success} success, {total_failed} failed.'
        ))
