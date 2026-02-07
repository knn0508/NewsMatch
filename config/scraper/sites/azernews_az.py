import requests
from scraper.models import Article
from bs4 import BeautifulSoup


def scrape_articles(url=None):
    """Scrape latest articles from azernews.az homepage."""
    homepage = 'https://www.azernews.az'
    response = requests.get(homepage, timeout=10)
    soup = BeautifulSoup(response.content, 'html.parser')

    links = set()
    for a in soup.find_all('a', href=True):
        href = a['href']
        if href.endswith('.html') and href.startswith('https://www.azernews.az/'):
            links.add(href)

    # Skip articles already in DB
    existing_urls = set(Article.objects.filter(url__in=links).values_list('url', flat=True))
    new_links = links - existing_urls

    for link in new_links:
        try:
            title, date, image_url, content = azernews_scrape(link)
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


def azernews_scrape(link):
    response = requests.get(link, timeout=10)
    soup = BeautifulSoup(response.content, 'html.parser')
    content_main = soup.find('div', class_='article-content-wrapper')
    if not content_main:
        return None, None, None, None
    title_tag = content_main.find('h2')
    title = title_tag.text.strip() if title_tag else None
    date_tag = content_main.find('span', class_='me-3')
    date = date_tag.text.strip() if date_tag else ''
    img_tag = content_main.find('img')
    image_url = img_tag['src'] if img_tag and img_tag.get('src') else ''
    content_div = content_main.find('div', class_='article-content')
    content = content_div.text.strip() if content_div else ''
    return title, date, image_url, content