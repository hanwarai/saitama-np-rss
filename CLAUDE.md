# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## プロジェクト概要

埼玉新聞のカテゴリページ `https://www.saitama-np.co.jp/categorys/news-original/topic/saitama`（県内NEWS / まちの話題 / さいたま）を **単一 Atom フィード** にして GitHub Pages で公開するスクリプト。購読 URL は `https://hanwarai.github.io/saitama-np-rss/feed.xml`。GitHub Actions が 1 日 1 回（00:00 UTC）に再ビルド → デプロイする。

姉妹プロジェクト `saitama-culture` / `tver-rss` と同じ構成。ソースサイトに公開 RSS が無いため自作する。サイトはサーバーサイドレンダリングの普通の HTML を返すので **playwright 不要**、`requests + beautifulsoup4 + lxml` で十分。

## 現状

レイアウト（`saitama-culture` をひな形）:

- `pyproject.toml` — Python 3.13、本体依存 `requests` / `feedgenerator` / `beautifulsoup4` / `lxml`。dev 依存に `ruff` / `mypy` / `pytest` / `pytest-cov` / `pre-commit` / `types-requests` / `types-beautifulsoup4`
- `.python-version`
- `.gitignore`（`/dist/` を ignore。`uv.lock` は **commit する**）
- `.pre-commit-config.yaml`（pre-commit-hooks + ruff + ruff-format + mypy）
- `main.py`（実装は下記）
- `tests/test_main.py`（pytest。カバレッジ閾値 80%）
- `.github/workflows/gh-pages.yaml`（push + 毎日 00:00 UTC cron でビルド & Pages デプロイ。**唯一のワークフロー**）
- `.github/dependabot.yml`（`github-actions` と `uv` を weekly、`commit-message.prefix: "ci"`）

`templates/` も `feeds/index.html` も **使わない**（単一フィードなので URL は `main.py` に直書き、出力は `feed.xml` 一本）。

出力先は `dist/feed.xml`。`actions/upload-pages-artifact` の `path: dist`。

## ソースサイトの HTML（重要）

GET `https://www.saitama-np.co.jp/categorys/news-original/topic/saitama` がそのまま記事リストの HTML を返す。SPA ではなくサーバーサイドレンダリング、JS 実行不要。

ページネーションは `?page=N`（1〜144）。**page=1 のみ取得**（リーダーには最新分だけで十分。ヒストリアーカイブ用途ではない）。1 ページに ~8 件。

サイトは **レスポンシブ HTML を二重実装** している。同じ記事リストが PC 用と SP 用で別々に出力されるため、両方拾うとアイテムが倍になる。`main.py` ではセレクタ `div.pc-only ul.newslist-1-grid > li` で **pc 側だけ**を採用する（`LIST_SELECTOR` 定数）。

各 `<li>` から取り出すフィールド:

| 取得元 | 用途 |
|---|---|
| `h2.newslist-1-tt > a` の `href` | 詳細 URL（`https://www.saitama-np.co.jp/articles/{id}` 形式の絶対 URL）→ `link` と `unique_id` (id 部) |
| `h2.newslist-1-tt > a` のテキスト | `title` |
| `div.newslist-1-date` のテキスト | `YYYY/MM/DD` 形式。JST 0:00 と解釈して UTC に変換 → `pubdate` |
| `div.newslist-1-picbox img[src]` | サムネ画像 URL（CDN 経由、絶対 URL）→ `media_thumbnail` |

詳細ページ本文は **取得しない**（リクエスト数を 1 回に抑える設計）。アイテム `description` は空文字。リーダー側は title + サムネ + 日付 + リンクで一覧表示する想定。

## アーキテクチャ（`main.py`）

1. `fetch_html()`: `requests.get(SOURCE_URL, headers=REQUEST_HEADERS, timeout=TIMEOUT)` → `raise_for_status` → `apparent_encoding` で文字化け回避してから `response.text` を返す
2. `parse_items(html)`: `BeautifulSoup(html, "lxml")` で `LIST_SELECTOR` を回し、各 `<li>` を `parse_item` に渡す。失敗したアイテムは `print("[ERROR] skipping ...")` でログだけ吐いて continue（1 件壊れても全体を落とさない）
3. `parse_item(li)` で title / link / pubdate / media_thumbnail を抽出
4. `build_feed(items)` → `AtomFeedWithMedia` に詰めて `dist/feed.xml` に書き出し

サムネイル画像は **`<media:thumbnail>`**（Media RSS, `xmlns:media="http://search.yahoo.com/mrss/"`）として出す。`feedgenerator.Atom1Feed` を継承した `AtomFeedWithMedia` で `root_attributes` に namespace を増やし、`add_item_elements` で `media:thumbnail` を吐く。アイテム側は `add_item(media_thumbnail=URL, ...)` で渡す（`saitama-culture` と同じ実装）。

`requests` 呼び出しには **必ず `timeout` と `raise_for_status`** を付ける（`fetch_html`）。

## コマンド

Python 3.13 系を `uv` で固定。

```bash
uv sync                     # 依存インストール (dev グループ含む)
uv run pre-commit install   # 初回のみ: git hook を有効化 (CI を置いてないため必須)
uv run main.py              # フィード生成: dist/feed.xml を出力
SSL_VERIFY=False uv run main.py  # 自己署名証明書環境用 (社内プロキシ等)
uv run ruff check .         # lint (mccabe 複雑度 10 まで含む)
uv run ruff format --check . # format チェック (修正は --check を外す)
uv run mypy                 # 型検査 (strict 寄り)
uv run pytest               # テスト + カバレッジ (cov-fail-under=80)
uv run pre-commit run --all-files
```

**CI ワークフローは置いていない**（`gh-pages.yaml` 単独）。lint / format / mypy / pytest は `pre-commit` のローカル実行で担保する方針。動作確認は `dist/feed.xml` がパースできること（例: `xmllint --noout dist/feed.xml`）と、`gh-pages.yaml` のビルドが通っていることで見る。

## デプロイ

`.github/workflows/gh-pages.yaml`（`saitama-culture` / `tver-rss` と同一テンプレート）:

- トリガー: `main` への push と毎日 00:00 UTC cron
- `astral-sh/setup-uv` → `actions/setup-python`（`python-version-file: pyproject.toml`）→ `uv sync` → `uv run main.py` → `actions/upload-pages-artifact`（path: `dist`）→ `actions/deploy-pages`
- `concurrency` を workflow 単位でまとめて、push と cron の競合を防ぐ

`dist/` 配下は `.gitignore` 済み（ランナー上で生成して直接 Pages にアップ）。git tracked な成果物はない。

購読 URL は `https://hanwarai.github.io/saitama-np-rss/feed.xml`。ルート (`/`) には `index.html` がないので 404 になる — リーダーには `feed.xml` の URL を直接渡す。

## Dependabot

`.github/dependabot.yml` で `github-actions` と `uv` を weekly 更新。`commit-message.prefix` は `ci`。`pip` ecosystem も登録されているが `open-pull-requests-limit: 0` で抑止（uv 経由で済むため重複 PR を避ける）。自動 PR レビュー (`claude.yml`) は置いていない。

## コミット慣例

`fix:` / `ci:` / `feat:` を日本語本文と併用（姉妹プロジェクトと統一）。

## 既知の落とし穴

- **`pc-only` / `sp-only` の二重 HTML**。何も考えず `ul.newslist-1-grid > li` で拾うとアイテムが倍になる。必ず `div.pc-only` 配下にスコープを切る (`LIST_SELECTOR` 定数で固定済み)
- **広告枠の `<li>` が混入する**（Geniee Wrapper など）。`ul.newslist-1-grid > li` で拾うと記事 li と区別なく取れる。`parse_items` で `h2.newslist-1-tt` を持たない `<li>` は静かにスキップしている（`[ERROR]` ログには出さない）。これを `[ERROR]` 扱いに戻すと毎日 2 行 noise が出るので注意
- 同じ `<li>` 内に `<a>` が 2 つ（タイトル用とサムネ用、両方とも記事詳細を指す）。`<h2 class="newslist-1-tt">` 配下の方を title/href の出処にする
- 日付は **`YYYY/MM/DD` のみ** で時刻情報なし。JST 0:00 とみなして UTC に変換している（`parse_date` 内）。同一日内の更新順は反映されない仕様
- `response.encoding` が空のまま入ってくることがあるため、`apparent_encoding` でフォールバックしてから `.text` を読む（`fetch_html`）。これを抜くと文字化けの可能性
- サイトに公式 RSS は無いため、HTML 構造が変わると無音で壊れる。`pc-only` クラス / `newslist-1-grid` クラスが変わったら全件 0 件になる — モニタリングは「`dist/feed.xml` のアイテム数 > 0」程度で十分
- ページネーションは `?page=N` で 144 ページまでだが、現状 page=1 のみ取得。週次の取りこぼし懸念があれば 2〜3 ページに増やす（その場合は per-page で `try/except` を分ける）
