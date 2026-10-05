"""
3つのニュースサイトから最新記事を集めて、テーマ別に分類し JSON に保存するスクリプト。

  1. 沖縄観光の実態
  2. DX推進のためのAI活用
  3. 宿泊業のための補助金施策

GitHub Actions が定期的に実行します（.github/workflows/update-news.yml）。
手元で試すとき:  python scripts/fetch_news.py

追加ライブラリは不要です（Python 標準ライブラリだけで動きます）。
"""

import email.utils
import html
import json
import re
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path

JST = timezone(timedelta(hours=9))
OUTPUT = Path(__file__).resolve().parent.parent / "dashboard" / "data" / "articles.json"

# 何日前までの記事を残すか / 1テーマあたりの最大件数
KEEP_DAYS = 120
MAX_PER_CATEGORY = 150

# ---------------------------------------------------------------------------
# 情報源（ここを編集すればサイトを増やせます）
# feeds: 直接読みにいく RSS の候補 URL（見つかったものを使う）
# ---------------------------------------------------------------------------
SOURCES = [
    {
        "id": "honichi",
        "name": "訪日ラボ",
        "home": "https://honichi.com/",
        "domain": "honichi.com",
        "feeds": [
            "https://honichi.com/feed/",
            "https://honichi.com/news/feed/",
            "https://honichi.com/rss/",
        ],
    },
    {
        "id": "hotelbank",
        "name": "HOTEL BANK",
        "home": "https://hotelbank.jp/",
        "domain": "hotelbank.jp",
        "feeds": [
            "https://hotelbank.jp/feed/",
            "https://hotelbank.jp/rss/",
        ],
    },
    {
        "id": "travelvoice",
        "name": "トラベルボイス",
        "home": "https://www.travelvoice.jp/",
        "domain": "travelvoice.jp",
        "feeds": [
            "https://www.travelvoice.jp/feed",
            "https://www.travelvoice.jp/feed/",
            "https://www.travelvoice.jp/rss",
            "https://www.travelvoice.jp/index.rdf",
        ],
    },
]

# ---------------------------------------------------------------------------
# テーマと分類キーワード（タイトル・概要にどれか1つでも含まれれば、そのテーマに入る）
# search: Google ニュースで「サイト内検索」するときの語（新着RSSに出てこない記事も拾うため）
# ---------------------------------------------------------------------------
CATEGORIES = [
    {
        "id": "okinawa",
        "keywords": [
            "沖縄", "那覇", "石垣", "宮古", "八重山", "久米島", "恩納", "名護",
            "北谷", "読谷", "本部町", "やんばる", "美ら海", "首里", "琉球",
            "OCVB", "沖縄観光コンベンション", "Okinawa",
        ],
        "search": ["沖縄"],
    },
    {
        "id": "dx_ai",
        "keywords": [
            "AI", "生成AI", "ChatGPT", "Gemini", "Claude", "LLM", "人工知能",
            "DX", "デジタル化", "デジタルトランスフォーメーション", "自動化",
            "省人化", "省力化", "スマートホテル", "セルフチェックイン", "チャットボット",
            "PMS", "SaaS", "ロボット", "データ活用",
        ],
        "search": ["AI", "DX"],
    },
    {
        "id": "subsidy",
        "keywords": [
            "補助金", "助成金", "補助事業", "支援事業", "交付金", "給付金",
            "公募", "高付加価値化", "省力化投資", "事業再構築", "IT導入",
            "ものづくり補助", "持続化補助", "支援制度", "補助率",
        ],
        "search": ["補助金", "支援事業 宿泊"],
    },
]

USER_AGENT = (
    "Mozilla/5.0 (compatible; okinawa-private-guide-bot/1.0; "
    "+https://github.com/itsukinishihira/okinawa-private-guide)"
)

NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "dc": "http://purl.org/dc/elements/1.1/",
    "content": "http://purl.org/rss/1.0/modules/content/",
    "rss1": "http://purl.org/rss/1.0/",
}


def log(msg):
    print(msg, file=sys.stderr)


def fetch(url, timeout=25):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as res:
        raw = res.read()
        charset = res.headers.get_content_charset() or "utf-8"
    return raw, charset


def clean_text(s, limit=None):
    """HTMLタグを取り除き、空白を整える"""
    if not s:
        return ""
    s = re.sub(r"<[^>]+>", " ", s)
    s = html.unescape(s)
    s = re.sub(r"\s+", " ", s).strip()
    if limit and len(s) > limit:
        s = s[:limit].rstrip() + "…"
    return s


def parse_date(s):
    """RSS / Atom のいろいろな日付形式を ISO 形式（日本時間）に変換"""
    if not s:
        return None
    s = s.strip()
    try:
        dt = email.utils.parsedate_to_datetime(s)  # RSS 2.0 形式
    except (TypeError, ValueError):
        dt = None
    if dt is None:
        try:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))  # Atom / dc:date 形式
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=JST)
    return dt.astimezone(JST).isoformat(timespec="minutes")


def _text(el, path):
    found = el.find(path, NS)
    return found.text if found is not None and found.text else ""


def parse_feed(raw):
    """RSS 2.0 / RSS 1.0 (RDF) / Atom を読み、記事のリストを返す"""
    root = ET.fromstring(raw)
    items = []

    # RSS 2.0
    for it in root.iter("item"):
        items.append({
            "title": _text(it, "title"),
            "url": _text(it, "link"),
            "published": parse_date(_text(it, "pubDate") or _text(it, "dc:date")),
            "summary": _text(it, "description") or _text(it, "content:encoded"),
            "tags": [c.text for c in it.findall("category") if c.text],
        })
    # RSS 1.0 (RDF)
    for it in root.iter("{%s}item" % NS["rss1"]):
        items.append({
            "title": _text(it, "rss1:title"),
            "url": _text(it, "rss1:link"),
            "published": parse_date(_text(it, "dc:date")),
            "summary": _text(it, "rss1:description"),
            "tags": [c.text for c in it.findall("dc:subject", NS) if c.text],
        })
    # Atom
    for it in root.iter("{%s}entry" % NS["atom"]):
        link = ""
        for l in it.findall("atom:link", NS):
            if l.get("rel", "alternate") == "alternate":
                link = l.get("href", "")
                break
        items.append({
            "title": _text(it, "atom:title"),
            "url": link,
            "published": parse_date(_text(it, "atom:published") or _text(it, "atom:updated")),
            "summary": _text(it, "atom:summary") or _text(it, "atom:content"),
            "tags": [c.get("term") for c in it.findall("atom:category", NS) if c.get("term")],
        })
    return items


class FeedLinkFinder(HTMLParser):
    """トップページの <link rel="alternate" type="application/rss+xml"> を探す"""

    def __init__(self):
        super().__init__()
        self.links = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "link" and "alternate" in (a.get("rel") or "") and \
                ("rss" in (a.get("type") or "") or "atom" in (a.get("type") or "")):
            if a.get("href"):
                self.links.append(a["href"])


def discover_feeds(source):
    try:
        raw, charset = fetch(source["home"])
    except Exception as e:  # noqa: BLE001
        log(f"  [{source['id']}] トップページ取得失敗: {e}")
        return []
    finder = FeedLinkFinder()
    finder.feed(raw.decode(charset, errors="replace"))
    return [urllib.parse.urljoin(source["home"], h) for h in finder.links]


def from_site_feed(source):
    """サイト自身の RSS から新着記事を取得"""
    tried = set()
    candidates = list(source["feeds"])
    discovered = False
    while candidates:
        url = candidates.pop(0)
        if url in tried:
            continue
        tried.add(url)
        try:
            raw, _ = fetch(url)
            items = parse_feed(raw)
        except Exception as e:  # noqa: BLE001
            log(f"  [{source['id']}] {url} -> 失敗 ({e})")
            items = []
        if items:
            log(f"  [{source['id']}] {url} -> {len(items)}件")
            return items
        if not candidates and not discovered:
            discovered = True
            candidates.extend(discover_feeds(source))
    return []


def from_google_news(source, query):
    """Google ニュースの『サイト内検索』RSS で、テーマに合う記事を補完取得"""
    q = f"{query} site:{source['domain']} when:90d"
    url = "https://news.google.com/rss/search?" + urllib.parse.urlencode(
        {"q": q, "hl": "ja", "gl": "JP", "ceid": "JP:ja"}
    )
    try:
        raw, _ = fetch(url)
        items = parse_feed(raw)
    except Exception as e:  # noqa: BLE001
        log(f"  [{source['id']}] Googleニュース「{query}」-> 失敗 ({e})")
        return []
    # Google ニュースのタイトル末尾「 - サイト名」を取り除く
    for it in items:
        it["title"] = re.sub(r"\s+-\s+[^-]+$", "", it["title"] or "")
        it["summary"] = ""  # Google ニュースの概要はリンクの羅列なので使わない
    log(f"  [{source['id']}] Googleニュース「{query}」-> {len(items)}件")
    return items


def categorize(title, summary, tags):
    text = " ".join([title, summary, " ".join(tags)])
    cats = []
    for c in CATEGORIES:
        for kw in c["keywords"]:
            # 英字の短い語（AI, DX など）は単語の一部に誤ヒットしないよう境界をチェック
            if re.fullmatch(r"[A-Za-z]+", kw):
                if re.search(r"(?<![A-Za-z])" + kw + r"(?![A-Za-z])", text):
                    cats.append(c["id"])
                    break
            elif kw in text:
                cats.append(c["id"])
                break
    return cats


def normalize_url(url):
    p = urllib.parse.urlsplit(url.strip())
    query = urllib.parse.urlencode(
        [(k, v) for k, v in urllib.parse.parse_qsl(p.query) if not k.startswith("utm_")]
    )
    return urllib.parse.urlunsplit((p.scheme, p.netloc, p.path, query, ""))


def load_previous():
    if OUTPUT.exists():
        try:
            return json.loads(OUTPUT.read_text(encoding="utf-8")).get("articles", [])
        except (json.JSONDecodeError, OSError):
            pass
    return []


def main():
    now = datetime.now(JST)
    collected = {}
    source_status = []

    for src in SOURCES:
        log(f"■ {src['name']}")
        raw_items = from_site_feed(src)
        ok_feed = bool(raw_items)
        for c in CATEGORIES:
            for q in c["search"]:
                raw_items += from_google_news(src, q)

        count = 0
        for it in raw_items:
            title = clean_text(it.get("title"))
            url = (it.get("url") or "").strip()
            if not title or not url:
                continue
            summary = clean_text(it.get("summary"), limit=160)
            cats = categorize(title, summary, it.get("tags") or [])
            if not cats:
                continue  # 3テーマのどれにも当てはまらない記事は載せない
            key = title  # Google ニュース経由と直接 RSS で URL が違うことがあるのでタイトルで重複判定
            prev = collected.get(key)
            item = {
                "title": title,
                "url": normalize_url(url),
                "source": src["id"],
                "published": it.get("published"),
                "summary": summary,
                "categories": cats,
            }
            if prev:
                # 直接 RSS の URL（元記事）と概要を優先して残す
                if "news.google.com" in prev["url"] and "news.google.com" not in item["url"]:
                    prev["url"] = item["url"]
                prev["summary"] = prev["summary"] or item["summary"]
                prev["published"] = prev["published"] or item["published"]
                prev["categories"] = sorted(set(prev["categories"]) | set(cats))
            else:
                collected[key] = item
                count += 1
        source_status.append({"id": src["id"], "name": src["name"], "home": src["home"],
                              "direct_feed": ok_feed, "new_items": count})

    # 前回までに集めた記事とまとめる（サイト側で取得できなかった回も記事が消えないように）
    cutoff = (now - timedelta(days=KEEP_DAYS)).isoformat()
    for old in load_previous():
        if old["title"] not in collected:
            collected[old["title"]] = old

    articles = [a for a in collected.values()
                if not a.get("published") or a["published"] >= cutoff]
    articles.sort(key=lambda a: a.get("published") or "", reverse=True)

    # テーマごとの上限を超えた古い記事を削る
    kept, per_cat = [], {c["id"]: 0 for c in CATEGORIES}
    for a in articles:
        if any(per_cat[c] < MAX_PER_CATEGORY for c in a["categories"]):
            kept.append(a)
            for c in a["categories"]:
                per_cat[c] += 1

    total_new = sum(s["new_items"] for s in source_status)
    if total_new == 0:
        # 取得に全部失敗したときは、前回のデータをそのまま残す（更新日時もごまかさない）
        log("記事を1件も取得できませんでした。前回のデータを残して終了します。")
        sys.exit(1)

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps({
        "updated_at": now.isoformat(timespec="minutes"),
        "sources": source_status,
        "articles": kept,
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    log(f"保存しました: {OUTPUT} （{len(kept)}件）")


if __name__ == "__main__":
    main()
