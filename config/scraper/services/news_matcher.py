"""
News matching service — pure text search with translated aliases.

MATCHING STRATEGY (priority order):
1. **Title/description text match** — keyword OR any of its translated aliases
   found (case-insensitive, whole word) in article title or description
   → automatic match (score 1.0).
2. **Content text match** — keyword/alias found in article content in a real
   sentence (>50 chars) → match (score 0.95).  Filters out nav/sidebar junk.

No semantic embedding matching — translations are handled by pre-generated
aliases via ``deep-translator`` (Google Translate).  When a user adds keyword
"Azerbaijan", the system auto-translates it into:
    Azerbaijan, Azərbaycan, Azerbaycan, Азербайджан, أذربيجان, ...
and text-matches against ALL of those.  100% accurate, no false positives.

Usage:
    >>> from scraper.services.news_matcher import NewsMatcherService
    >>> matcher = NewsMatcherService()
    >>> matches = matcher.match_article_to_keywords(article)
    >>> for m in matches:
    ...     print(m['user_id'], m['keyword'], m['similarity'])
"""

from __future__ import annotations

import logging
import re
from datetime import timedelta
from typing import Any

from django.utils import timezone

logger = logging.getLogger('scraper')

# Footer / boilerplate patterns — lines matching these are NOT real article
# content and must never trigger keyword matches.  They appear on every page
# of a news site (address, copyright, contact info, social links, …).
_FOOTER_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r'(?i)^\s*ünvan\s*:', re.UNICODE),
    re.compile(r'(?i)^\s*(tel|fax|telefon|e-?mail|əlaqə)\s*:', re.UNICODE),
    re.compile(r'(?:©|\(c\)|copyright)', re.IGNORECASE),
    re.compile(r'(?i)all\s+rights\s+reserved|bütün\s+hüquqlar', re.UNICODE),
    re.compile(r'(?i)saytdakı\s+materiallardan', re.UNICODE),
    re.compile(r'(?i)xəbərlərdən\s+istifadə\s+edərkən', re.UNICODE),
    re.compile(r'(?i)istinad\s+mütləqdir', re.UNICODE),
    re.compile(r'(?i)məlumat\s+üçün.*redaksiya', re.UNICODE),
    re.compile(r'(?i)(powered|developed|designed)\s+by', re.UNICODE),
    re.compile(r'(?i)bizi\s+(izləyin|sosial)', re.UNICODE),
]


def _whole_word_match(keyword: str, text: str) -> bool:
    """
    Check if *keyword* appears as a whole word in *text* (case-insensitive).

    Uses word-boundary regex so "şəki" does NOT match "şəkil",
    but DOES match "Şəki şəhərində" or "about Şəki.".
    """
    pattern = r'(?i)\b' + re.escape(keyword) + r'\b'
    return bool(re.search(pattern, text))


def _any_alias_match(aliases: list[str], text: str) -> str | None:
    """
    Check if any alias from the list matches as a whole word in *text*.

    Returns the first matching alias, or None if no match.
    """
    for alias in aliases:
        if _whole_word_match(alias, text):
            return alias
    return None


class NewsMatcherService:
    """
    Match articles with user keywords using pure text search + aliases.

    When a user adds a keyword, it's automatically translated into multiple
    languages (en, az, tr, ru, ar, fr, de).  The matcher checks the article
    against the original keyword AND all its aliases.

    Example:
        >>> matcher = NewsMatcherService()
        >>> matches = matcher.match_article_to_keywords(article)
    """

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def match_article_to_keywords(self, article: Any) -> list[dict[str, Any]]:
        """
        Find all user keywords that match *article*.

        Strategy (for each keyword + its aliases):
        1. Any alias in article TITLE or DESCRIPTION → match (score 1.0)
        2. Any alias in article CONTENT in a real sentence → match (score 0.95)

        Args:
            article: A ``NewsArticle`` model instance.

        Returns:
            List of dicts with keys: ``user_id``, ``keyword``, ``similarity``,
            ``evidence``, ``keyword_in_text``, ``match_type``.
        """
        from scraper.models import UserKeyword

        title = (article.title or '').strip()
        content = (article.content or '').strip()
        description = (article.description or '').strip()

        # Skip very short articles
        if len(content) < 100:
            logger.debug("Article %d too short (%d chars) — skip", article.id, len(content))
            return []

        user_keywords = UserKeyword.objects.all()
        if not user_keywords.exists():
            return []

        matches: list[dict[str, Any]] = []

        for uk in user_keywords:
            kw = uk.keyword.strip()
            # Build the full list of text variants to check
            aliases = uk.keyword_aliases or []
            if not aliases:
                # Fallback: no aliases generated yet, use just the keyword
                aliases = [kw]
            elif kw not in aliases:
                aliases = [kw] + aliases

            # ── METHOD 1: Any alias in TITLE or DESCRIPTION ──
            title_match = _any_alias_match(aliases, title)
            desc_match = _any_alias_match(aliases, description)

            if title_match or desc_match:
                matched_alias = title_match or desc_match
                found_in = []
                if title_match:
                    found_in.append('title')
                if desc_match:
                    found_in.append('description')
                found_str = ', '.join(found_in)
                snippet = title if title_match else description[:200]

                is_translation = matched_alias.lower() != kw.lower()
                match_label = f'translation "{matched_alias}"' if is_translation else 'exact'

                matches.append({
                    'user_id': uk.user_id,
                    'keyword': kw,
                    'similarity': 1.0,
                    'evidence': f'Found "{matched_alias}" ({match_label}) in {found_str}: "{snippet[:150]}"',
                    'keyword_in_text': True,
                    'match_type': f'text ({found_str})',
                })
                logger.info(
                    "TEXT MATCH: article %d '%s' <-> user %d keyword '%s' (alias='%s', in %s)",
                    article.id, title[:40], uk.user_id, kw, matched_alias, found_str,
                )
                continue

            # ── METHOD 2: Any alias in CONTENT (real sentences only) ──
            content_match = _any_alias_match(aliases, content)
            if content_match:
                real_sentence = self._find_real_sentence(content, content_match)
                if real_sentence:
                    is_translation = content_match.lower() != kw.lower()
                    match_label = f'translation "{content_match}"' if is_translation else 'exact'

                    matches.append({
                        'user_id': uk.user_id,
                        'keyword': kw,
                        'similarity': 0.95,
                        'evidence': f'Found "{content_match}" ({match_label}) in content: "{real_sentence[:150]}"',
                        'keyword_in_text': True,
                        'match_type': 'text (content)',
                    })
                    logger.info(
                        "CONTENT MATCH: article %d '%s' <-> user %d keyword '%s' (alias='%s')",
                        article.id, title[:40], uk.user_id, kw, content_match,
                    )
                    continue
                else:
                    logger.debug(
                        "Alias '%s' found in article %d content but only in nav/junk — skipping",
                        content_match, article.id,
                    )

        matches.sort(key=lambda x: x['similarity'], reverse=True)
        logger.info(
            "Article %d: %d matches found (%d keywords checked)",
            article.id, len(matches), user_keywords.count(),
        )
        return matches

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _is_junk_line(line: str) -> bool:
        """
        Check if a line is navigation / sidebar / related-article junk
        rather than actual article body text.
        """
        # Lines starting with common junk markers
        if line.startswith('[') or line.startswith('!') or line.startswith('*'):
            return True
        # Markdown headings that are entirely a link to another article
        # e.g. ### [Azərbaycan və ABŞ ...](https://sia.az/az/news/...)
        if re.match(r'^#{1,6}\s*\[.+\]\(https?://.+\)', line):
            return True
        # Lines that contain a markdown link taking up most of the line
        # (related article teasers embedded in content)
        link_match = re.search(r'\[([^\]]+)\]\(https?://[^)]+\)', line)
        if link_match:
            link_text_len = len(link_match.group(0))
            # If the link occupies >70% of the line, it's likely a nav link
            if link_text_len > 0.7 * len(line):
                return True
        # Sidebar category + time lines like "Siyasət 21:07"
        if re.match(r'^[A-ZÇĞİÖŞÜА-Я][a-zA-ZçğıöşüÇĞİÖŞÜа-яА-Я\-]+\s+\d{1,2}:\d{2}$', line):
            return True
        # Footer / boilerplate lines (address, copyright, contact info)
        if any(pat.search(line) for pat in _FOOTER_PATTERNS):
            return True
        return False

    @staticmethod
    def _find_real_sentence(content: str, keyword: str, min_len: int = 50) -> str | None:
        """
        Find a *real* sentence in content that contains the keyword.

        Returns the sentence if it's at least ``min_len`` chars (meaning it's
        actual article text, not a nav link like "[Prezident 327]").
        Returns ``None`` if the keyword only appears in junk/nav text.

        Filters out:
        - Lines starting with [, !, * (links, images, lists)
        - Markdown headings that are links to other articles
        - Lines dominated by markdown links (>70% link text)
        - Sidebar category/time labels
        """
        lines = content.split('\n')
        for line in lines:
            line = line.strip()
            if len(line) < min_len:
                continue
            if NewsMatcherService._is_junk_line(line):
                continue
            if _whole_word_match(keyword, line):
                sentences = re.split(r'(?<=[.!?])\s+', line)
                for s in sentences:
                    if _whole_word_match(keyword, s) and len(s.strip()) >= min_len:
                        return s.strip()[:200]
                if len(line) >= min_len:
                    return line[:200]
        return None

    def match_keyword_to_articles(
        self, user_keyword: Any, recent_days: int = 7, max_results: int = 20,
    ) -> list[dict[str, Any]]:
        """
        Find recent articles that match a given user keyword (+ aliases).

        Args:
            user_keyword: A ``UserKeyword`` model instance.
            recent_days: Only consider articles from the last N days.
            max_results: Max results to return.

        Returns:
            List of dicts ``{'article_id': int, 'title': str, 'url': str,
            'similarity': float}`` sorted by descending similarity.
        """
        from scraper.models import NewsArticle

        cutoff = timezone.now() - timedelta(days=recent_days)
        articles = NewsArticle.objects.filter(scraped_at__gte=cutoff)

        if not articles.exists():
            return []

        kw = user_keyword.keyword.strip()
        aliases = user_keyword.keyword_aliases or []
        if not aliases:
            aliases = [kw]
        elif kw not in aliases:
            aliases = [kw] + aliases

        results: list[dict[str, Any]] = []

        for article in articles:
            title = (article.title or '').strip()
            content = (article.content or '').strip()
            description = (article.description or '').strip()

            # ── Title or description match ──
            if _any_alias_match(aliases, title) or _any_alias_match(aliases, description):
                results.append({
                    'article_id': article.id,
                    'title': article.title,
                    'url': article.url,
                    'similarity': 1.0,
                })
                continue

            # ── Content match (real sentences only) ──
            content_match = _any_alias_match(aliases, content)
            if content_match:
                if self._find_real_sentence(content, content_match):
                    results.append({
                        'article_id': article.id,
                        'title': article.title,
                        'url': article.url,
                        'similarity': 0.95,
                    })
                    continue

        results.sort(key=lambda x: x['similarity'], reverse=True)
        return results[:max_results]
