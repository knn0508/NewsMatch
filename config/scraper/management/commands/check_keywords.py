from django.core.management.base import BaseCommand
from scraper.models import UserKeyword, NewsArticle


class Command(BaseCommand):
    help = 'Check all user keywords against recent articles using semantic matching'

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS('Checking all semantic keywords against recent articles...'))

        keywords = UserKeyword.objects.all()
        if not keywords.exists():
            self.stdout.write(self.style.WARNING('No user keywords found.'))
            return

        self.stdout.write(f'Found {keywords.count()} keyword(s)')

        try:
            from scraper.services.news_matcher import NewsMatcherService
            matcher = NewsMatcherService()

            total_matches = 0
            for kw in keywords:
                if not kw.has_embedding:
                    self.stdout.write(f'  ⏳ Skipping "{kw.keyword}" — no embedding yet')
                    continue

                matches = matcher.match_keyword_to_articles(kw, recent_days=7)
                total_matches += len(matches)
                if matches:
                    self.stdout.write(self.style.SUCCESS(
                        f'  🧠 "{kw.keyword}" (user {kw.user_id}): {len(matches)} match(es)'
                    ))
                else:
                    self.stdout.write(f'  "{kw.keyword}" (user {kw.user_id}): no matches')

            self.stdout.write(self.style.SUCCESS(f'\n✓ Done. Total matches: {total_matches}'))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'Error: {e}'))
