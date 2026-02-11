"""
Jina AI Reader service for intelligent web scraping.

Uses Jina AI's free Reader API (https://r.jina.ai/) to scrape news websites
without manual CSS selectors. Jina AI automatically:

- Renders JavaScript content
- Removes ads, navigation, and footers
- Returns clean markdown
- Adapts to website HTML changes

FREE tier: 1M tokens/month (no API key required for basic usage).

Usage:
    >>> from scraper.services.jina_scraper import JinaScraperService
    >>> scraper = JinaScraperService()
    >>> result = scraper.scrape_url("https://example.com/article")
    >>> print(result['title'], result['content'][:100])
"""

from __future__ import annotations

import logging
import re
import time
from typing import Any, Optional
from urllib.parse import urljoin, urlparse

import requests
from django.conf import settings

logger = logging.getLogger('scraper')

# Default timeout for HTTP requests (seconds)
_DEFAULT_TIMEOUT: int = getattr(settings, 'SCRAPE_TIMEOUT', 30)

# Maximum articles to scrape from a single homepage
_MAX_ARTICLES: int = getattr(settings, 'MAX_ARTICLES_PER_SCRAPE', 20)

# Known boilerplate / site-wide meta descriptions that should be replaced
# with an auto-extracted summary from the article content.
_BOILERPLATE_DESCRIPTIONS: list[str] = [
    'azərbaycan və dünyada baş verən hadisələr haqqında operativ xəbərləri fasiləsiz çatdırır',
    'xəbərlə bitmir, foto, video, peşəkar reportyor araşdırması',
    'müəllif layihələri və əyləncə',
    'dünya və yerli xəbərlərin tək ünvanı',
]

# Patterns that indicate a line is website footer / boilerplate text
# (address, copyright, contact info, social links, etc.).
# These appear on EVERY page and must not be used for keyword matching.
_FOOTER_PATTERNS: list[re.Pattern[str]] = [
    # Physical address lines:  "Ünvan: ..., Bakı, Azərbaycan"
    re.compile(r'(?i)^\s*ünvan\s*:', re.UNICODE),
    # Tel / Fax / Email lines
    re.compile(r'(?i)^\s*(tel|fax|telefon|e-?mail|əlaqə)\s*:', re.UNICODE),
    # Copyright lines:  "© 2024 Sia.az", "All rights reserved"
    re.compile(r'(?:©|\(c\)|copyright)', re.IGNORECASE),
    re.compile(r'(?i)all\s+rights\s+reserved|bütün\s+hüquqlar', re.UNICODE),
    # Common AZ news site footer phrases
    re.compile(r'(?i)saytdakı\s+materiallardan', re.UNICODE),
    re.compile(r'(?i)xəbərlərdən\s+istifadə\s+edərkən', re.UNICODE),
    re.compile(r'(?i)istinad\s+mütləqdir', re.UNICODE),
    re.compile(r'(?i)məlumat\s+üçün.*redaksiya', re.UNICODE),
    # "Powered by" / "Developed by" type lines
    re.compile(r'(?i)(powered|developed|designed)\s+by', re.UNICODE),
    # Social media prompts at the end
    re.compile(r'(?i)bizi\s+(izləyin|sosial)', re.UNICODE),
]


class JinaScraperService:
    """
    Scrape websites using Jina AI Reader (100 % FREE, no API key needed).

    The service communicates with ``https://r.jina.ai/{url}``.

    - **Homepage scraping** uses ``Accept: text/markdown`` to extract article links.
    - **Article scraping** uses ``Accept: application/json`` so Jina returns
      structured data with the **real** article title, description, and content.

    Args:
        api_key: Optional Jina API key for higher rate limits.

    Example:
        >>> svc = JinaScraperService()
        >>> article = svc.scrape_url("https://azenews.az/article/123")
        >>> article['title']
        'Şəki şəhərində yeni park açıldı'
    """

    JINA_READER_URL: str = getattr(settings, 'JINA_READER_URL', 'https://r.jina.ai/')

    def __init__(self, api_key: str | None = None) -> None:
        self.api_key = api_key or getattr(settings, 'JINA_API_KEY', '')
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'MediaTrends/1.0',
        })
        if self.api_key:
            self.session.headers['Authorization'] = f'Bearer {self.api_key}'

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def scrape_url(self, url: str, options: dict[str, Any] | None = None) -> dict[str, Any]:
        """
        Scrape a single article URL via Jina AI Reader (JSON mode).

        Uses ``Accept: application/json`` so Jina returns structured data
        with the **real** page title, description, and clean content.

        Args:
            url: The target URL to scrape.
            options: Optional dict of extra query-params for the Jina API.

        Returns:
            A dict with keys:
            ``title``, ``content``, ``description``, ``url``,
            ``publish_date``, ``author``, ``success`` (bool).
        """
        jina_url = f"{self.JINA_READER_URL}{url}"
        logger.info("Scraping URL via Jina AI (JSON): %s", url)

        try:
            headers = {'Accept': 'application/json'}
            response = self.session.get(
                jina_url, timeout=_DEFAULT_TIMEOUT,
                params=options or {}, headers=headers,
            )
            response.raise_for_status()

            data = response.json()

            # Jina JSON response: {"code": 200, "data": {"title": ..., "content": ..., ...}}
            jina_data = data.get('data', {})
            title = jina_data.get('title', '').strip()
            content = jina_data.get('content', '').strip()
            description = jina_data.get('description', '').strip()

            if not content or len(content) < 50:
                logger.warning("Jina returned empty/very short content for %s", url)
                return self._error_result(url, "Empty content returned by Jina")

            # Clean content: remove navigation/menu junk from the top
            cleaned_content = self._clean_article_content(content)

            # Extract publish date and author from content text
            publish_date = self._extract_publish_date(content)
            author = self._extract_author(content)

            # Extract category from URL path (e.g. /nation/254198.html -> Nation)
            category = self._extract_category_from_url(url)

            # Detect boilerplate / site-wide meta descriptions and replace
            # with a meaningful summary extracted from the article content.
            if self._is_boilerplate_description(description):
                description = self._extract_description_from_content(cleaned_content)
                logger.debug(
                    "Replaced boilerplate description with content extract for %s", url,
                )

            return {
                'title': title[:500] if title else '',
                'content': cleaned_content,
                'description': description[:1000] if description else '',
                'url': jina_data.get('url', url),
                'article_link': jina_data.get('url', url),
                'publish_date': publish_date,
                'author': author,
                'category': category,
                'success': True,
            }

        except (ValueError, KeyError) as exc:
            # JSON parse error — fall back to markdown mode
            logger.warning("Jina JSON parse failed for %s, falling back to markdown: %s", url, exc)
            return self._scrape_url_markdown(url, options)
        except requests.exceptions.Timeout:
            logger.error("Timeout scraping %s", url)
            return self._error_result(url, "Request timed out")
        except requests.exceptions.HTTPError as exc:
            logger.error("HTTP error scraping %s: %s", url, exc)
            return self._error_result(url, f"HTTP {exc.response.status_code}")
        except requests.exceptions.RequestException as exc:
            logger.error("Request error scraping %s: %s", url, exc)
            return self._error_result(url, str(exc))

    def _scrape_url_markdown(self, url: str, options: dict[str, Any] | None = None) -> dict[str, Any]:
        """
        Fallback: scrape a URL using markdown mode and parse manually.
        """
        jina_url = f"{self.JINA_READER_URL}{url}"
        try:
            headers = {'Accept': 'text/markdown'}
            response = self.session.get(
                jina_url, timeout=_DEFAULT_TIMEOUT,
                params=options or {}, headers=headers,
            )
            response.raise_for_status()

            markdown = response.text
            if not markdown or len(markdown.strip()) < 50:
                return self._error_result(url, "Empty markdown content")

            parsed = self._parse_jina_markdown(markdown, url)
            parsed['success'] = True
            return parsed
        except Exception as exc:
            logger.error("Markdown fallback also failed for %s: %s", url, exc)
            return self._error_result(url, str(exc))

    def scrape_multiple_articles(self, base_url: str) -> list[dict[str, Any]]:
        """
        Scrape a news homepage and then each linked article.

        1. Fetches the homepage via Jina AI to get markdown.
        2. Extracts article links from the markdown.
        3. Scrapes each article individually (up to ``MAX_ARTICLES_PER_SCRAPE``).

        Args:
            base_url: The homepage URL of the news source.

        Returns:
            A list of article dicts (same schema as ``scrape_url``).
        """
        logger.info("Scraping homepage for article links: %s", base_url)

        # Step 1 — Scrape homepage in MARKDOWN mode to extract links
        homepage = self._scrape_url_markdown(base_url)
        if not homepage.get('success'):
            logger.error("Failed to scrape homepage: %s", base_url)
            return []

        # Step 2 — Extract article URLs from the markdown
        article_urls = self._extract_article_urls(homepage.get('content', ''), base_url)
        logger.info("Found %d article URLs on %s", len(article_urls), base_url)

        if not article_urls:
            return []

        # Step 3 — Scrape each article via JSON mode (gets real title)
        articles: list[dict[str, Any]] = []
        for idx, article_url in enumerate(article_urls[:_MAX_ARTICLES]):
            logger.info("Scraping article %d/%d: %s", idx + 1, min(len(article_urls), _MAX_ARTICLES), article_url)
            result = self.scrape_url(article_url)  # uses JSON mode → correct title
            if result.get('success'):
                articles.append(result)
            # Be polite — small delay between requests
            time.sleep(1)

        logger.info("Successfully scraped %d articles from %s", len(articles), base_url)
        return articles

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _parse_jina_markdown(self, markdown: str, original_url: str) -> dict[str, Any]:
        """
        Parse Jina AI's markdown response into a structured dict.

        Extracts title (first ``#`` heading), description (first paragraph),
        publish date (regex), and author if mentioned.

        Args:
            markdown: Raw markdown text from Jina.
            original_url: The URL that was scraped.

        Returns:
            Dict with ``title``, ``content``, ``description``, ``url``,
            ``publish_date``, ``author``.
        """
        lines = markdown.strip().split('\n')

        # --- Title: first H1 heading ---
        title = ''
        for line in lines:
            stripped = line.strip()
            if stripped.startswith('# '):
                title = stripped.lstrip('# ').strip()
                break
        if not title:
            # Fallback: first non-empty line
            for line in lines:
                if line.strip():
                    title = line.strip()[:200]
                    break

        # --- Description: first substantial paragraph ---
        description = ''
        for line in lines:
            stripped = line.strip()
            if stripped and not stripped.startswith('#') and len(stripped) > 40:
                description = stripped[:500]
                break

        # --- Publish date: regex patterns ---
        publish_date = self._extract_publish_date(markdown)

        # --- Author ---
        author = self._extract_author(markdown)

        # --- Content: full markdown, cleaned ---
        content = self._clean_content(markdown)

        # Replace boilerplate description with content extract
        if self._is_boilerplate_description(description):
            description = self._extract_description_from_content(content)

        return {
            'title': title,
            'content': content,
            'description': description,
            'url': original_url,
            'publish_date': publish_date,
            'author': author,
        }

    def _extract_article_urls(self, markdown: str, base_url: str) -> list[str]:
        """
        Extract unique article URLs from markdown text.

        Finds markdown links ``[text](url)``, resolves relative URLs,
        and filters to the same domain.

        Args:
            markdown: Markdown content (typically a homepage).
            base_url: The base URL for resolving relative links.

        Returns:
            A deduplicated list of absolute article URLs.
        """
        parsed_base = urlparse(base_url)
        base_domain = parsed_base.netloc.removeprefix('www.')

        # Find all markdown links: [text](url)
        link_pattern = re.compile(r'\[([^\]]+)\]\(([^)]+)\)')
        matches = link_pattern.findall(markdown)

        seen: set[str] = set()
        urls: list[str] = []

        _SKIP_EXTENSIONS = (
            '.jpg', '.jpeg', '.png', '.gif', '.svg', '.webp', '.avif', '.ico',
            '.css', '.js', '.pdf', '.mp3', '.mp4', '.avi', '.mov', '.wmv',
            '.zip', '.rar', '.exe', '.woff', '.woff2', '.ttf', '.eot',
        )

        for link_text, href in matches:
            href_lower = href.lower()
            # Skip non-article links (images, media, anchors, resources)
            if any(href_lower.endswith(ext) for ext in _SKIP_EXTENSIONS):
                continue
            if href.startswith('#') or href.startswith('mailto:') or href.startswith('javascript:'):
                continue
            # Skip if the link text itself looks like a media filename
            if re.search(r'\.(webp|jpg|jpeg|png|gif|svg|avif|mp4|pdf)\b', link_text, re.IGNORECASE):
                continue

            # Resolve relative URLs
            absolute_url = urljoin(base_url, href)
            parsed_link = urlparse(absolute_url)

            # Same-domain filter (handle www vs non-www)
            link_domain = parsed_link.netloc.removeprefix('www.')
            if link_domain != base_domain:
                continue

            path = parsed_link.path

            # Skip homepage itself
            if path in ('/', ''):
                continue

            # ARTICLE FILTER: real article URLs contain digits
            # e.g. /nation/254198.html, /business/12345, /news/2024/01/article-slug
            # Category pages like /nation/, /business/ do NOT contain digits
            if not re.search(r'\d', path):
                continue

            # Skip very short paths
            if len(path) < 5:
                continue

            if absolute_url not in seen:
                seen.add(absolute_url)
                urls.append(absolute_url)

        return urls

    @staticmethod
    def _extract_publish_date(text: str) -> str | None:
        """
        Attempt to find a publish date in the text using common patterns.

        Returns an ISO-format string or ``None``.
        """
        date_patterns = [
            # 2024-01-15, 2024/01/15
            r'(\d{4}[-/]\d{1,2}[-/]\d{1,2})',
            # 15 January 2024, 15 Jan 2024
            r'(\d{1,2}\s+(?:January|February|March|April|May|June|July|August|September|October|November|December|Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{4})',
            # January 15, 2024
            r'((?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+\d{4})',
            # 15.01.2024
            r'(\d{1,2}\.\d{1,2}\.\d{4})',
        ]
        for pattern in date_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return match.group(1).strip()
        return None

    @staticmethod
    def _extract_author(text: str) -> str:
        """
        Attempt to find an author name in the text.

        Looks for patterns like "By Author Name" or "Author: Name".
        """
        author_patterns = [
            r'(?:By|Author|Written by|Reporter)[:\s]+([A-Z][a-zA-ZÇçĞğİıÖöŞşÜü\s\-\.]{2,40})',
            r'(?:Müəllif|Jurnalist)[:\s]+([A-ZÇĞİÖŞÜ][a-zA-ZçğıöşüÇĞİÖŞÜ\s\-\.]{2,40})',
        ]
        for pattern in author_patterns:
            match = re.search(pattern, text)
            if match:
                return match.group(1).strip()
        return ''

    @staticmethod
    def _clean_content(markdown: str) -> str:
        """
        Clean markdown content for storage.

        Removes excessive blank lines and leading/trailing whitespace while
        preserving meaningful structure.
        """
        # Collapse 3+ consecutive blank lines into 2
        cleaned = re.sub(r'\n{3,}', '\n\n', markdown)
        return cleaned.strip()

    @staticmethod
    def _clean_article_content(content: str) -> str:
        """
        Remove navigation/header junk from the beginning of article content,
        and related-article / sidebar links from the end and middle.

        Jina Reader returns the full page markdown including site navigation,
        login links, category menus, and "related articles" sections that
        link to other stories on the same site.  If those links mention
        keywords the user tracks, they cause false-positive matches.
        """
        lines = content.split('\n')

        # Find the first substantial paragraph (not heading, link, list, image, >60 chars)
        body_start = 0
        for i, line in enumerate(lines):
            stripped = line.strip()
            if (
                stripped
                and not stripped.startswith('#')
                and not stripped.startswith('*')
                and not stripped.startswith('[')
                and not stripped.startswith('!')
                and not stripped.startswith('---')
                and '======' not in stripped
                and '------' not in stripped
                and len(stripped) > 60
            ):
                body_start = i
                break

        body_lines = lines[body_start:]

        # Remove junk lines: images, nav-style list items, and related-article links
        cleaned_lines: list[str] = []
        for line in body_lines:
            stripped = line.strip()
            # Skip image lines
            if stripped.startswith('!['):
                continue
            # Skip short nav-style list items with links
            if stripped.startswith('*') and '[' in stripped and '](' in stripped and len(stripped) < 80:
                continue
            # Skip markdown headings that are entirely a link to another article
            # e.g. ### [Some other article title](https://sia.az/az/news/...)
            if re.match(r'^#{1,6}\s*\[.+\]\(https?://.+\)\s*$', stripped):
                continue
            # Skip standalone link lines (entire line is a markdown link)
            if re.match(r'^\[.+\]\(https?://.+\)\s*$', stripped) and len(stripped) < 200:
                continue
            # Skip lines that look like sidebar category headers
            # e.g. "Siyasət 21:07", "Dünya 20:34"
            if re.match(r'^[A-ZÇĞİÖŞÜА-Я][a-zA-ZçğıöşüÇĞİÖŞÜа-яА-Я\-]+\s+\d{1,2}:\d{2}$', stripped):
                continue
            # Skip footer / boilerplate lines (address, copyright, contact)
            if any(pat.search(stripped) for pat in _FOOTER_PATTERNS):
                continue
            cleaned_lines.append(line)

        result = '\n'.join(cleaned_lines)
        result = re.sub(r'\n{3,}', '\n\n', result)
        return result.strip()

    @staticmethod
    def _extract_category_from_url(url: str) -> str:
        """
        Extract the news category from a URL path.

        Examples:
            https://azernews.az/nation/254198.html  -> "Nation"
            https://apa.az/en/business/article-slug  -> "Business"
        """
        parsed = urlparse(url)
        parts = [p for p in parsed.path.split('/') if p]

        if not parts:
            return ''

        # First path segment is usually the category
        candidate = parts[0]

        # Skip if it's a number or a short language code like "en", "az"
        if candidate.isdigit() or len(candidate) <= 2:
            if len(parts) > 1:
                candidate = parts[1]
            else:
                return ''

        # Skip if it looks like a file (e.g. 254198.html)
        if re.search(r'\d{3,}', candidate):
            return ''

        return candidate.replace('-', ' ').replace('_', ' ').title()

    @staticmethod
    def _is_boilerplate_description(description: str) -> bool:
        """Check if the description is a generic site-wide boilerplate.

        Many Azerbaijani news sites (e.g. sia.az) use the same
        ``<meta name="description">`` on every page instead of an
        article-specific summary.  This helper detects those.
        """
        if not description:
            return False
        desc_lower = description.lower().strip()
        return any(phrase in desc_lower for phrase in _BOILERPLATE_DESCRIPTIONS)

    @staticmethod
    def _extract_description_from_content(content: str, max_len: int = 500) -> str:
        """Extract a meaningful description from article content.

        Takes the first substantial paragraph (>60 chars, not a heading
        or link) as the description.
        """
        for line in content.split('\n'):
            stripped = line.strip()
            if (
                stripped
                and not stripped.startswith('#')
                and not stripped.startswith('[')
                and not stripped.startswith('!')
                and not stripped.startswith('*')
                and not stripped.startswith('---')
                and len(stripped) > 60
            ):
                # Remove markdown formatting
                cleaned = re.sub(r'\*\*(.+?)\*\*', r'\1', stripped)
                cleaned = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', cleaned)
                return cleaned[:max_len]
        # Fallback: first 500 chars of content, stripped of markdown
        fallback = re.sub(r'[#*\[\]!]', '', content).strip()
        return fallback[:max_len] if fallback else ''

    @staticmethod
    def _error_result(url: str, error_msg: str) -> dict[str, Any]:
        """Return a failure result dict."""
        return {
            'title': '',
            'content': '',
            'description': '',
            'url': url,
            'publish_date': None,
            'author': '',
            'success': False,
            'error': error_msg,
        }
