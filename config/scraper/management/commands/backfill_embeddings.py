"""
Management command: Backfill embeddings for existing data.

Generates embeddings for all ``NewsArticle`` and ``UserKeyword`` records
that don't have one yet, using batch processing for efficiency.

Usage:
    python manage.py backfill_embeddings
    python manage.py backfill_embeddings --batch-size 50
    python manage.py backfill_embeddings --articles-only
    python manage.py backfill_embeddings --keywords-only
"""

from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = 'Generate embeddings for existing articles and keywords that lack them.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--batch-size',
            type=int,
            default=32,
            help='Number of texts to embed per batch (default: 32).',
        )
        parser.add_argument(
            '--articles-only',
            action='store_true',
            default=False,
            help='Only backfill article embeddings.',
        )
        parser.add_argument(
            '--keywords-only',
            action='store_true',
            default=False,
            help='Only backfill keyword embeddings.',
        )

    def handle(self, *args, **options):
        batch_size = options['batch_size']
        articles_only = options['articles_only']
        keywords_only = options['keywords_only']

        try:
            from scraper.services.embedding_service import EmbeddingService

            svc = EmbeddingService()
            self.stdout.write(self.style.SUCCESS('✓ Embedding model loaded'))
        except Exception as exc:
            raise CommandError(f'Failed to load embedding model: {exc}')

        stats = {'articles': 0, 'keywords': 0, 'errors': 0}

        # ── Articles ──
        if not keywords_only:
            stats['articles'] = self._backfill_articles(svc, batch_size)

        # ── Keywords ──
        if not articles_only:
            stats['keywords'] = self._backfill_keywords(svc, batch_size)

        self.stdout.write(self.style.SUCCESS(
            f'\n✓ Backfill complete: '
            f'{stats["articles"]} articles, '
            f'{stats["keywords"]} keywords.'
        ))

    def _backfill_articles(self, svc, batch_size: int) -> int:
        """Backfill embeddings for articles without them."""
        from scraper.models import NewsArticle

        articles = NewsArticle.objects.filter(content_embedding__isnull=True)
        total = articles.count()

        if total == 0:
            self.stdout.write('  No articles need embeddings.')
            return 0

        self.stdout.write(f'  Processing {total} articles …')
        processed = 0

        # Process in batches
        for start in range(0, total, batch_size):
            batch = list(articles[start:start + batch_size])
            texts = [f"{a.title}\n\n{a.content}" for a in batch]

            try:
                embeddings = svc.get_embeddings_batch(texts)

                for article, embedding in zip(batch, embeddings):
                    if embedding and not all(v == 0.0 for v in embedding):
                        article.content_embedding = embedding
                        article.save(update_fields=['content_embedding'])
                        processed += 1
            except Exception as exc:
                self.stderr.write(f'  ✗ Batch error at offset {start}: {exc}')

            self.stdout.write(f'  … {min(start + batch_size, total)}/{total}')

        self.stdout.write(self.style.SUCCESS(f'  ✓ {processed}/{total} article embeddings generated'))
        return processed

    def _backfill_keywords(self, svc, batch_size: int) -> int:
        """Backfill embeddings for keywords without them."""
        from scraper.models import UserKeyword

        keywords = UserKeyword.objects.filter(keyword_embedding__isnull=True)
        total = keywords.count()

        if total == 0:
            self.stdout.write('  No keywords need embeddings.')
            return 0

        self.stdout.write(f'  Processing {total} keywords …')
        processed = 0

        for start in range(0, total, batch_size):
            batch = list(keywords[start:start + batch_size])
            texts = [f"News article about {kw.keyword}" for kw in batch]

            try:
                embeddings = svc.get_embeddings_batch(texts)

                for kw, embedding in zip(batch, embeddings):
                    if embedding and not all(v == 0.0 for v in embedding):
                        kw.keyword_embedding = embedding
                        kw.save(update_fields=['keyword_embedding'])
                        processed += 1
            except Exception as exc:
                self.stderr.write(f'  ✗ Batch error at offset {start}: {exc}')

            self.stdout.write(f'  … {min(start + batch_size, total)}/{total}')

        self.stdout.write(self.style.SUCCESS(f'  ✓ {processed}/{total} keyword embeddings generated'))
        return processed
