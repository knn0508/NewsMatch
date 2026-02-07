import requests
from scraper.models import Article
from bs4 import BeautifulSoup


def scrape_articles(url='https://apa.az/rss'):
    """Scrape articles from APA RSS feed."""
    response = requests.get(url, timeout=10)
    soup = BeautifulSoup(response.content, features='xml')

    articles = soup.find_all('item')

    # Collect all links first
    links = set()
    for item in articles:
        link_tag = item.find('link')
        if link_tag:
            links.add(link_tag.text.strip())

    # Skip articles already in DB
    existing_urls = set(Article.objects.filter(url__in=links).values_list('url', flat=True))
    new_links = links - existing_urls

    for link in new_links:
        try:
            title, date, image_url, content = apa_scrape(link)
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


def apa_scrape(link):
    response = requests.get(link, timeout=10)
    soup = BeautifulSoup(response.content, 'html.parser')
    content_main = soup.find('div', class_='content_main')
    if not content_main:
        return None, None, None, None
    title_tag = content_main.find('h2', class_='title_news')
    title = title_tag.text.strip() if title_tag else None
    img_div = content_main.find('div', class_='main_img')
    image_url = img_div.find('img')['src'] if img_div and img_div.find('img') else ''
    content_div = content_main.find('div', class_='news_content mt-site')
    content = content_div.text.strip() if content_div else ''
    date_div = content_main.find('div', class_='date')
    date = date_div.text.strip() if date_div else ''
    return title, date, image_url, content