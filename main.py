import datetime
import os
import re
from pathlib import Path
from typing import Any

import feedgenerator
import requests
from bs4 import BeautifulSoup, Tag

SOURCE_URL = "https://www.saitama-np.co.jp/categorys/news-original/topic/saitama"
SITE_BASE = "https://www.saitama-np.co.jp"

FEED_TITLE = "埼玉新聞 まちの話題 さいたま"
FEED_DESCRIPTION = "埼玉新聞 県内NEWS / まちの話題 / さいたま カテゴリの最新記事"
FEED_LANGUAGE = "ja"

# サイトはレスポンシブ HTML を pc-only / sp-only の二重実装で配信しており、
# 両方拾うと記事が倍になる。pc 側を正規データセットとして 1 回だけ拾う。
LIST_SELECTOR = "div.pc-only ul.newslist-1-grid > li"

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36 "
    "(KHTML, like Gecko) saitama-np-rss/0.1 (+https://github.com/hanwarai/saitama-np-rss)"
)
REQUEST_HEADERS = {"User-Agent": USER_AGENT}

JST = datetime.timezone(datetime.timedelta(hours=9))
TIMEOUT = (5, 30)
SSL_VERIFY = os.getenv("SSL_VERIFY", "True") == "True"

ARTICLE_ID_RE = re.compile(r"/articles/(\d+)")
DATE_RE = re.compile(r"^\s*(\d{4})/(\d{2})/(\d{2})\s*$")

OUTPUT_PATH = Path("dist") / "feed.xml"


def fetch_html() -> str:
    response = requests.get(
        SOURCE_URL,
        headers=REQUEST_HEADERS,
        timeout=TIMEOUT,
        verify=SSL_VERIFY,
    )
    response.raise_for_status()
    response.encoding = response.apparent_encoding or "utf-8"
    return response.text


def parse_date(raw: str) -> datetime.datetime:
    """`YYYY/MM/DD` (JST 0:00 想定) を UTC datetime に変換する."""
    m = DATE_RE.match(raw)
    if not m:
        raise ValueError(f"invalid date format: {raw!r}")
    year, month, day = (int(p) for p in m.groups())
    naive = datetime.datetime(year, month, day)
    return naive.replace(tzinfo=JST).astimezone(datetime.UTC)


def extract_article_id(href: str) -> str:
    m = ARTICLE_ID_RE.search(href)
    if not m:
        raise ValueError(f"no article id in href: {href!r}")
    return m.group(1)


def parse_item(li: Tag) -> dict[str, Any]:
    title_a = li.select_one("h2.newslist-1-tt a")
    if not isinstance(title_a, Tag):
        raise ValueError("missing title anchor")
    href_raw = title_a.get("href")
    if not isinstance(href_raw, str) or not href_raw:
        raise ValueError("missing href")
    title = title_a.get_text(strip=True)
    if not title:
        raise ValueError("empty title")

    date_div = li.select_one("div.newslist-1-date")
    if not isinstance(date_div, Tag):
        raise ValueError("missing date div")
    pubdate = parse_date(date_div.get_text())

    thumbnail: str | None = None
    img = li.select_one("div.newslist-1-picbox img")
    if isinstance(img, Tag):
        src = img.get("src")
        if isinstance(src, str) and src:
            thumbnail = src

    # 記事 URL であることを検証 (非記事リンクは ValueError で弾く)
    extract_article_id(href_raw)
    item: dict[str, Any] = {
        # feedgenerator は unique_id をそのまま Atom の <id> に出す。多くのリーダーが
        # <id> をパーマリンクとして扱うため、絶対 URL (= link) を入れる。bare な
        # 記事 ID だとフィード URL に相対解決され 404 リンクになる
        "unique_id": href_raw,
        "title": title,
        "link": href_raw,
        "description": "",
        "pubdate": pubdate,
    }
    if thumbnail is not None:
        item["media_thumbnail"] = thumbnail
    return item


def parse_items(html: str) -> list[dict[str, Any]]:
    soup = BeautifulSoup(html, "lxml")
    items: list[dict[str, Any]] = []
    for li in soup.select(LIST_SELECTOR):
        # 記事リストに広告枠の <li> が混ざる (Geniee 等)。h2.newslist-1-tt を
        # 持たないものは記事ではないので静かにスキップ。本物のパース失敗 (タイトル
        # 抽出失敗など) だけが [ERROR] ログに残るようにする
        if not li.select_one("h2.newslist-1-tt"):
            continue
        try:
            items.append(parse_item(li))
        except ValueError as exc:
            print(f"[ERROR] skipping list item: {exc}")
    return items


class AtomFeedWithMedia(feedgenerator.Atom1Feed):
    """Atom1Feed + Media RSS namespace で `<media:thumbnail>` を出すラッパ."""

    def root_attributes(self) -> dict[str, str]:
        attrs: dict[str, str] = super().root_attributes()
        attrs["xmlns:media"] = "http://search.yahoo.com/mrss/"
        return attrs

    def add_item_elements(self, handler: Any, item: dict[str, Any]) -> None:
        super().add_item_elements(handler, item)
        thumbnail = item.get("media_thumbnail")
        if thumbnail:
            handler.addQuickElement("media:thumbnail", "", {"url": thumbnail})


def build_feed(items: list[dict[str, Any]]) -> AtomFeedWithMedia:
    feed = AtomFeedWithMedia(
        title=FEED_TITLE,
        link=SOURCE_URL,
        description=FEED_DESCRIPTION,
        language=FEED_LANGUAGE,
    )
    for item in items:
        feed.add_item(content="", **item)
    return feed


def main() -> None:
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    feed = build_feed(parse_items(fetch_html()))
    with OUTPUT_PATH.open("w", encoding="utf-8") as fp:
        feed.write(fp, "utf-8")
    print(f"wrote {OUTPUT_PATH} ({OUTPUT_PATH.stat().st_size} bytes, {len(feed.items)} items)")


if __name__ == "__main__":
    main()
