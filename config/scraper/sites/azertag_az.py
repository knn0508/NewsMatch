import requests
from scraper.models import Article
from bs4 import BeautifulSoup

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
}


def scrape_articles(url=None):
    """Scrape latest articles from azertag.az news listing."""
    response = requests.get('https://azertag.az/xeber', timeout=10, headers=HEADERS)
    soup = BeautifulSoup(response.content, 'html.parser')

    links = set()
    for a in soup.find_all('a', href=True):
        href = a['href']
        if '/xeber/' in href and href != '/xeber/':
            full_url = f'https://azertag.az{href}' if href.startswith('/') else href
            links.add(full_url)

    # Skip articles already in DB
    existing_urls = set(Article.objects.filter(url__in=links).values_list('url', flat=True))
    new_links = links - existing_urls

    for link in new_links:
        try:
            title, date, image_url, content = azertag_scrape(link)
            if title and content:
                Article.objects.get_or_create(
                    url=link,
                    defaults={
                        'title': title,
                        'image_url': image_url,
                        'content': content,
                        'date': date,
                    }
                )
        except Exception:
            continue


def azertag_scrape(link):
    response = requests.get(link, timeout=10, headers=HEADERS)
    soup = BeautifulSoup(response.content, 'html.parser')

    title_tag = soup.find('h1', class_='entry-title') or soup.find('h2', class_='entry-title')
    title = title_tag.text.strip() if title_tag else None

    content_div = soup.find('div', class_='news-body') or soup.find('div', class_='news-text')
    content = ' '.join(p.text.strip() for p in content_div.find_all('p')) if content_div else ''

    meta_img = soup.find('meta', property='og:image')
    image_url = meta_img['content'] if meta_img else ''

    meta_div = soup.find('div', class_='entry-meta') or soup.find('div', class_='news-date')
    date = meta_div.get_text(strip=True) if meta_div else ''

    return title, date, image_url, content