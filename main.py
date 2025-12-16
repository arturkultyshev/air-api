from fastapi import FastAPI
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime, timedelta
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from bs4 import BeautifulSoup
import requests

TENGRI_TAG_URL = "https://tengrinews.kz/tag/%D0%B7%D0%B0%D0%B3%D1%80%D1%8F%D0%B7%D0%BD%D0%B5%D0%BD%D0%B8%D0%B5/"

app = FastAPI()

class NewsArticleOut(BaseModel):
    title: Optional[str]
    link: Optional[str]
    pubDate: Optional[str]
    description: Optional[str]
    content: Optional[str]
    image_url: Optional[str]
    source_id: Optional[str]

class NewsResponseOut(BaseModel):
    results: List[NewsArticleOut]

_cache_data: Optional[NewsResponseOut] = None
_cache_expires: Optional[datetime] = None
CACHE_TTL = timedelta(minutes=30)

import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0 Safari/537.36"
    )
}

def parse_article_details(url: str) -> dict:
    """
    Загружает страницу статьи и вытаскивает:
    pubDate, description, content, image_url.
    """
    try:
        resp = requests.get(url, headers=HEADERS, timeout=10)
        resp.raise_for_status()
    except Exception:
        return {
            "pubDate": None,
            "description": None,
            "content": None,
            "image_url": None,
        }

    soup = BeautifulSoup(resp.text, "lxml")

    # 1) дата публикации (есть в хлебных крошках рядом с заголовком)
    pub_date = None
    # в разметке это тот самый "16 декабря 2025, 12:37" из хлебных крошек
    breadcrumb = soup.find("ol") or soup.find("nav")
    if breadcrumb:
        for li in breadcrumb.find_all(["li", "span"], recursive=True):
            txt = li.get_text(" ", strip=True)
            if "202" in txt or "2025" in txt or "2024" in txt:
                pub_date = txt
                break

    # 2) описание
    description = None
    meta_desc = soup.find("meta", {"name": "description"})
    if meta_desc and meta_desc.get("content"):
        description = meta_desc["content"]

    # 3) основной текст статьи (параграфы)
    content = None
    # в примере текст идёт сразу под заголовком в основном блоке
    # пробуем несколько возможных контейнеров
    for cls in ["tn-news-text", "tn-article-text", "tn-article-body"]:
        main = soup.find("div", class_=cls)
        if main:
            paragraphs = [
                p.get_text(" ", strip=True) for p in main.find_all("p")
            ]
            content = "\n\n".join(p for p in paragraphs if p)
            break

    # fallback: если не нашли специальный div — берём все <p> в main
    if content is None:
        ps = soup.find_all("p")
        if ps:
            content = "\n\n".join(p.get_text(" ", strip=True) for p in ps)

    # 4) картинка
    image_url = None
    og_image = soup.find("meta", {"property": "og:image"})
    if og_image and og_image.get("content"):
        image_url = og_image["content"]

    return {
        "pubDate": pub_date,
        "description": description,
        "content": content or description,
        "image_url": image_url,
    }



def fetch_tengri_news() -> NewsResponseOut:
    resp = requests.get(TENGRI_TAG_URL, headers=HEADERS, timeout=10)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "lxml")

    items: List[NewsArticleOut] = []
    seen_links: set[str] = set()

    # Берём ВСЕ <a>, фильтруем только /kazakhstan_news/
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "/kazakhstan_news/" not in href:
            continue

        # делаем абсолютную ссылку
        if href.startswith("/"):
            link = urljoin("https://tengrinews.kz", href)
        else:
            link = href

        if link in seen_links:
            continue

        title = a.get_text(strip=True)
        if not title:
            continue

        # подтягиваем детали статьи
        details = parse_article_details(link)

        item = NewsArticleOut(
            title=title,
            link=link,
            pubDate=details["pubDate"],
            description=details["description"],
            content=details["content"],
            image_url=details["image_url"],
            source_id="tengrinews",
        )

        items.append(item)
        seen_links.add(link)

    print("FOUND ITEMS:", len(items))
    return NewsResponseOut(results=items)


def get_cached_news() -> NewsResponseOut:
    global _cache_data, _cache_expires
    now = datetime.utcnow()
    if _cache_data is not None and _cache_expires is not None and now < _cache_expires:
        return _cache_data

    data = fetch_tengri_news()
    _cache_data = data
    _cache_expires = now + CACHE_TTL
    return data


@app.get("/news/air-pollution", response_model=NewsResponseOut)
def get_air_pollution_news(limit: int = 20):
    data = get_cached_news()
    if limit > 0:
        data.results = data.results[:limit]
    return data
