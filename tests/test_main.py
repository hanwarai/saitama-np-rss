import datetime
import io
import pathlib
from typing import Any
from unittest.mock import patch

import pytest
from bs4 import BeautifulSoup, Tag

import main


def _make_li(html: str) -> Tag:
    soup = BeautifulSoup(html, "lxml")
    li = soup.find("li")
    assert isinstance(li, Tag)
    return li


SAMPLE_LIST_HTML = """
<html><body>
  <div class="pc-only">
    <ul class="newslist-1-grid">
      <li>
        <h2 class="newslist-1-tt">
          <a href="https://www.saitama-np.co.jp/articles/196026">記事タイトル A</a>
        </h2>
        <div class="newslist-1-date newsdate">2026/05/14</div>
        <div class="newslist-1-picbox news-picbox">
          <a href="https://www.saitama-np.co.jp/articles/196026" class="news-pic">
            <img src="https://www.saitama-np.co.jp/upload/images/A.jpg" alt="A">
          </a>
        </div>
      </li>
      <li>
        <h2 class="newslist-1-tt">
          <a href="https://www.saitama-np.co.jp/articles/195384">記事タイトル B</a>
        </h2>
        <div class="newslist-1-date newsdate">2026/05/10</div>
        <div class="newslist-1-picbox news-picbox">
          <a href="https://www.saitama-np.co.jp/articles/195384" class="news-pic">
            <img src="https://www.saitama-np.co.jp/upload/images/B.jpg" alt="B">
          </a>
        </div>
      </li>
    </ul>
  </div>
  <!-- sp-only は同じ記事の重複セット。pc-only だけ拾うので無視されるべき -->
  <div class="sp-only">
    <ul class="newslist-1-grid">
      <li>
        <h2 class="newslist-1-tt">
          <a href="https://www.saitama-np.co.jp/articles/196026">記事タイトル A (sp)</a>
        </h2>
        <div class="newslist-1-date newsdate">2026/05/14</div>
      </li>
    </ul>
  </div>
</body></html>
"""


def test_parse_date_returns_utc() -> None:
    dt = main.parse_date("2026/05/14")
    assert dt.tzinfo == datetime.UTC
    # JST 00:00 == UTC 前日 15:00
    assert dt == datetime.datetime(2026, 5, 13, 15, 0, tzinfo=datetime.UTC)


def test_parse_date_rejects_bad_format() -> None:
    with pytest.raises(ValueError, match="invalid date format"):
        main.parse_date("not-a-date")


def test_extract_article_id_from_full_url() -> None:
    assert main.extract_article_id("https://www.saitama-np.co.jp/articles/196026") == "196026"


def test_extract_article_id_raises_when_missing() -> None:
    with pytest.raises(ValueError, match="no article id"):
        main.extract_article_id("https://www.saitama-np.co.jp/about")


def test_parse_item_extracts_all_fields() -> None:
    li = _make_li(
        """
        <li>
          <h2 class="newslist-1-tt"><a href="https://www.saitama-np.co.jp/articles/123">タイトル</a></h2>
          <div class="newslist-1-date newsdate">2026/05/14</div>
          <div class="newslist-1-picbox">
            <img src="https://example.com/thumb.jpg">
          </div>
        </li>
        """
    )
    item = main.parse_item(li)
    assert item["unique_id"] == "123"
    assert item["title"] == "タイトル"
    assert item["link"] == "https://www.saitama-np.co.jp/articles/123"
    assert item["pubdate"] == datetime.datetime(2026, 5, 13, 15, 0, tzinfo=datetime.UTC)
    assert item["media_thumbnail"] == "https://example.com/thumb.jpg"


def test_parse_item_without_thumbnail_omits_media_thumbnail() -> None:
    li = _make_li(
        """
        <li>
          <h2 class="newslist-1-tt"><a href="https://www.saitama-np.co.jp/articles/123">タイトル</a></h2>
          <div class="newslist-1-date newsdate">2026/05/14</div>
        </li>
        """
    )
    item = main.parse_item(li)
    assert "media_thumbnail" not in item


def test_parse_item_raises_on_missing_title() -> None:
    li = _make_li(
        """
        <li>
          <div class="newslist-1-date newsdate">2026/05/14</div>
        </li>
        """
    )
    with pytest.raises(ValueError, match="missing title"):
        main.parse_item(li)


def test_parse_item_raises_on_empty_title() -> None:
    li = _make_li(
        """
        <li>
          <h2 class="newslist-1-tt"><a href="https://www.saitama-np.co.jp/articles/1"></a></h2>
          <div class="newslist-1-date newsdate">2026/05/14</div>
        </li>
        """
    )
    with pytest.raises(ValueError, match="empty title"):
        main.parse_item(li)


def test_parse_item_raises_on_missing_href() -> None:
    li = _make_li(
        """
        <li>
          <h2 class="newslist-1-tt"><a>タイトル</a></h2>
          <div class="newslist-1-date newsdate">2026/05/14</div>
        </li>
        """
    )
    with pytest.raises(ValueError, match="missing href"):
        main.parse_item(li)


def test_parse_item_raises_on_missing_date() -> None:
    li = _make_li(
        """
        <li>
          <h2 class="newslist-1-tt"><a href="https://www.saitama-np.co.jp/articles/1">タイトル</a></h2>
        </li>
        """
    )
    with pytest.raises(ValueError, match="missing date"):
        main.parse_item(li)


def test_parse_items_ignores_sp_only_duplicates() -> None:
    items = main.parse_items(SAMPLE_LIST_HTML)
    ids = [it["unique_id"] for it in items]
    # pc-only セットの 2 件のみ。sp-only 側はセレクタで除外
    assert ids == ["196026", "195384"]


def test_parse_items_silently_drops_ad_li(capsys: pytest.CaptureFixture[str]) -> None:
    # Geniee などの広告枠が記事 li に混ざる。h2.newslist-1-tt を持たないので
    # 静かにスキップされ、[ERROR] ログには出ない
    ad_html = """
    <div class="pc-only"><ul class="newslist-1-grid">
      <li><h2 class="newslist-1-tt"><a href="https://www.saitama-np.co.jp/articles/1">A</a></h2>
          <div class="newslist-1-date newsdate">2026/05/14</div></li>
      <li><div data-cptid="1539112"><script>/* ad */</script></div></li>
      <li><h2 class="newslist-1-tt"><a href="https://www.saitama-np.co.jp/articles/2">B</a></h2>
          <div class="newslist-1-date newsdate">2026/05/14</div></li>
    </ul></div>
    """
    items = main.parse_items(ad_html)
    assert [it["unique_id"] for it in items] == ["1", "2"]
    assert "[ERROR]" not in capsys.readouterr().out


def test_parse_items_skips_broken_entries(capsys: pytest.CaptureFixture[str]) -> None:
    broken_html = """
    <div class="pc-only"><ul class="newslist-1-grid">
      <li><h2 class="newslist-1-tt"><a href="https://www.saitama-np.co.jp/articles/1">OK</a></h2>
          <div class="newslist-1-date newsdate">2026/05/14</div></li>
      <li><h2 class="newslist-1-tt"><a href="https://www.saitama-np.co.jp/articles/2">NG</a></h2></li>
    </ul></div>
    """
    items = main.parse_items(broken_html)
    assert [it["unique_id"] for it in items] == ["1"]
    assert "skipping list item" in capsys.readouterr().out


def test_build_feed_emits_media_thumbnail_and_namespace() -> None:
    items = main.parse_items(SAMPLE_LIST_HTML)
    feed = main.build_feed(items)
    buf = io.StringIO()
    feed.write(buf, "utf-8")
    xml = buf.getvalue()
    assert 'xmlns:media="http://search.yahoo.com/mrss/"' in xml
    assert '<media:thumbnail url="https://www.saitama-np.co.jp/upload/images/A.jpg"' in xml
    assert "記事タイトル A" in xml
    assert "記事タイトル B" in xml


def test_fetch_html_passes_user_agent_and_timeout() -> None:
    class FakeResponse:
        text = "<html></html>"
        apparent_encoding = "utf-8"
        encoding = ""

        def raise_for_status(self) -> None:
            return None

    with patch("main.requests.get", return_value=FakeResponse()) as mock_get:
        html = main.fetch_html()

    assert html == "<html></html>"
    mock_get.assert_called_once()
    _, kwargs = mock_get.call_args
    assert kwargs["headers"]["User-Agent"].startswith("Mozilla/")
    assert kwargs["timeout"] == main.TIMEOUT


def test_main_writes_feed_xml(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = tmp_path / "dist" / "feed.xml"
    monkeypatch.setattr(main, "OUTPUT_PATH", output)
    monkeypatch.setattr(main, "fetch_html", lambda: SAMPLE_LIST_HTML)

    main.main()

    body = output.read_text(encoding="utf-8")
    assert body.startswith("<?xml")
    assert "196026" in body
    assert "195384" in body


def test_atom_feed_with_media_skips_thumbnail_when_absent() -> None:
    # media_thumbnail を含まないアイテムは <media:thumbnail> を吐かない
    feed = main.AtomFeedWithMedia(
        title="t",
        link=main.SOURCE_URL,
        description="d",
        language="ja",
    )
    feed.add_item(
        title="記事",
        link="https://www.saitama-np.co.jp/articles/1",
        description="",
        unique_id="1",
        pubdate=datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC),
    )
    buf = io.StringIO()
    feed.write(buf, "utf-8")
    assert "<media:thumbnail" not in buf.getvalue()


def test_fetch_html_falls_back_when_apparent_encoding_missing() -> None:
    class FakeResponse:
        text = "<html></html>"
        apparent_encoding: Any = None
        encoding = ""

        def raise_for_status(self) -> None:
            return None

    with patch("main.requests.get", return_value=FakeResponse()):
        assert main.fetch_html() == "<html></html>"
