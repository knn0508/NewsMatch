import requests
from config.scraper.models import Article
from bs4 import BeautifulSoup

def scrape_articles(url):
    response = requests.get(url)
    soup = BeautifulSoup(response.content, features="xml") 
    
    articles = soup.find_all('item')
    for item in articles:

        link = item.find('link').text
        if "azernews" in link:
            title, date, image_url, content = azernews_scrape(link)
        elif "apa" in link:
            title, date, image_url, content = apa_scrape(link)
        elif "azertag" in link:
            title, date, image_url, content = azertag_scrape(link)
             
        article, created = Article.objects.get_or_create(
        url=link, 
        defaults={
            'title': title,
            'image_url': image_url,
            'content': content,
            'date': date
        }
)
        

def azernews_scrape(link):
    response = requests.get(link)
    soup = BeautifulSoup(response.content,"html.parser") 
    content_main = soup.find('div', class_='article-content-wrapper')
    title = content_main.find('h2').text
    date = content_main.find('span', class_='me-3').text
    image_url = content_main.find('img')['src']
    content = content_main.find('div', class_='article-content').text
    return title , date, image_url, content

def apa_scrape(link):

        response = requests.get(link, timeout=5)
        soup = BeautifulSoup(response.content, "html.parser")
        content_main = soup.find('div', class_='content_main')
        title = content_main.find('h2', class_='title_news').text
        image_url = content_main.find('div', class_='main_img')['src']
        content = content_main.find('div', class_='news_content mt-site').text
        date = content_main.find('div', class_='date').text
        return title, date, image_url, content


def azertag_scrape(link):
    
    response = requests.get(link, timeout=10, headers=headers)
    soup = BeautifulSoup(response.content, "html.parser")

    title_tag = soup.find("h1", class_="entry-title") or soup.find("h2", class_="entry-title")
    title = title_tag.text.strip() if title_tag else "No title"

    meta_div = soup.find('div', class_='entry-meta') or soup.find('div', class_='news-date')
    date = meta_div.get_text(strip=True) if meta_div else "No date"

    content_div = soup.find("div", class_="news-body") or soup.find("div", class_="news-text")
    content = " ".join(p.text.strip() for p in content_div.find_all("p")) if content_div else "No content"

    meta_img = soup.find("meta", property="og:image")
    image_url = meta_img["content"] if meta_img else "No image"

    return title, date, image_url, content
