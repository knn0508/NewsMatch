"""
Translation service — generates keyword aliases in multiple languages.

Uses ``deep-translator`` (Google Translate) to translate a keyword into
target languages.  The aliases are stored on ``UserKeyword.keyword_aliases``
and used by the matcher for pure text search across languages.

Example:
    >>> svc = TranslationService()
    >>> svc.generate_aliases("Azerbaijan")
    ['Azerbaijan', 'Azərbaycan', 'Azerbaycan', 'Азербайджан', 'أذربيجان']
"""

from __future__ import annotations

import logging
from typing import Any

from django.conf import settings

logger = logging.getLogger('scraper')

# Target languages for translation.
# Each tuple: (language_code_for_deep_translator, human_label)
_TARGET_LANGUAGES: list[tuple[str, str]] = [
    ('en', 'English'),
    ('az', 'Azerbaijani'),
    ('tr', 'Turkish'),
    ('ru', 'Russian'),
    ('ar', 'Arabic'),
    ('fr', 'French'),
    ('de', 'German'),
]


class TranslationService:
    """Generate keyword aliases by translating into multiple languages."""

    def __init__(self, target_languages: list[tuple[str, str]] | None = None):
        self.target_languages = target_languages or _TARGET_LANGUAGES

    def generate_aliases(self, keyword: str) -> list[str]:
        """
        Translate *keyword* into all target languages and return unique aliases.

        Always includes the original keyword.  Duplicates and empty strings
        are removed.  Translation errors for individual languages are logged
        and skipped (never fatal).

        Args:
            keyword: The user's original keyword text.

        Returns:
            Deduplicated list of keyword variants (original + translations).
        """
        from deep_translator import GoogleTranslator

        aliases: set[str] = set()
        # Always include the original keyword (both as-is and lowercased)
        aliases.add(keyword.strip())

        for lang_code, lang_name in self.target_languages:
            try:
                translated = GoogleTranslator(source='auto', target=lang_code).translate(keyword)
                if translated and translated.strip():
                    cleaned = translated.strip()
                    # Skip if it's identical to the original
                    if cleaned.lower() != keyword.lower():
                        aliases.add(cleaned)
                        logger.debug(
                            "Translated '%s' -> %s: '%s'",
                            keyword, lang_name, cleaned,
                        )
            except Exception:
                logger.debug(
                    "Translation to %s failed for '%s' — skipping",
                    lang_name, keyword,
                )

        result = sorted(aliases)
        logger.info(
            "Generated %d aliases for keyword '%s': %s",
            len(result), keyword, result,
        )
        return result

    def update_keyword_aliases(self, user_keyword: Any) -> list[str]:
        """
        Generate aliases for a ``UserKeyword`` instance and save them.

        Args:
            user_keyword: A ``UserKeyword`` model instance.

        Returns:
            The list of generated aliases.
        """
        aliases = self.generate_aliases(user_keyword.keyword)
        user_keyword.keyword_aliases = aliases
        user_keyword.save(update_fields=['keyword_aliases'])
        logger.info(
            "Saved %d aliases for keyword '%s' (user %d)",
            len(aliases), user_keyword.keyword, user_keyword.user_id,
        )
        return aliases
