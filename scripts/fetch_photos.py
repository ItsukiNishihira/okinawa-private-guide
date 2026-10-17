"""
ゲストガイド用のスポット写真を Wikimedia Commons から取得します。

- images/photos.json に書かれた各スポットについて、
  1) "file" が指定されていればその写真を、
  2) 無ければ "category" / "search" から自動で 1 枚選びます。
- 再配布可能なライセンス（CC0 / パブリックドメイン / CC BY / CC BY-SA）のみ採用します。
- 横幅 1200px に縮小した JPEG を images/ に保存し、
  作者・ライセンス・出典 URL を images/credits.json に書き出します（クレジット表示用）。
- 候補一覧は images/candidates.json に出力します（差し替えの検討用）。
  PREVIEW_DIR を指定すると候補の縮小版も保存します（Actions の手動実行で preview を ON にすると
  photo-previews ブランチに保存されます）。

GitHub Actions（.github/workflows/fetch-photos.yml）から実行される想定です。
"""
import json
import os
import pathlib
import re
import time
import urllib.parse
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
IMG_DIR = ROOT / "images"
API = "https://commons.wikimedia.org/w/api.php"
UA = "okinawa-private-guide/1.0 (https://github.com/ItsukiNishihira/okinawa-private-guide)"
WIDTH = 1200
# 候補写真を見比べたいときは PREVIEW_DIR を指定すると、各スポットの候補の縮小版をそこへ保存します
PREVIEW_DIR = os.environ.get("PREVIEW_DIR")
ALLOWED = re.compile(r"^(CC0|Public domain|PD|CC BY(-SA)? [0-9.]+)", re.I)


def get(params):
    params = {**params, "format": "json", "formatversion": "2"}
    req = urllib.request.Request(API + "?" + urllib.parse.urlencode(params), headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def strip_html(s):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", s or "")).strip()


def info(titles):
    """ファイル名のリスト → 画像情報（ライセンス・作者・縮小 URL）"""
    out = []
    for i in range(0, len(titles), 40):
        data = get({
            "action": "query", "titles": "|".join(titles[i:i + 40]),
            "prop": "imageinfo", "iiprop": "url|size|mime|extmetadata", "iiurlwidth": WIDTH,
        })
        for p in data["query"]["pages"]:
            ii = (p.get("imageinfo") or [None])[0]
            if not ii or ii.get("mime") != "image/jpeg":
                continue
            m = ii.get("extmetadata", {})
            val = lambda k: strip_html(m.get(k, {}).get("value", ""))
            out.append({
                "title": p["title"],
                "width": ii["width"], "height": ii["height"],
                "thumb": ii.get("thumburl", ii["url"]),
                "page": ii["descriptionurl"],
                "license": val("LicenseShortName"),
                "license_url": val("LicenseUrl"),
                "artist": val("Artist") or "Unknown",
            })
    return out


def candidates(spot):
    titles = []
    if spot.get("category"):
        data = get({"action": "query", "list": "categorymembers", "cmtitle": "Category:" + spot["category"],
                    "cmtype": "file", "cmlimit": "200"})
        titles += [m["title"] for m in data["query"]["categorymembers"]]
    for q in spot.get("search", []):
        data = get({"action": "query", "list": "search", "srsearch": q, "srnamespace": "6", "srlimit": "50"})
        titles += [m["title"] for m in data["query"]["search"]]
    titles = list(dict.fromkeys(titles))
    return info(titles) if titles else []


def usable(c):
    ratio = c["width"] / max(c["height"], 1)
    return bool(ALLOWED.match(c["license"])) and c["width"] >= 1600 and 1.25 <= ratio <= 2.1


def download(url, dest):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=120) as r:
        dest.write_bytes(r.read())


def save_previews(out, cs):
    d = pathlib.Path(PREVIEW_DIR)
    d.mkdir(parents=True, exist_ok=True)
    stem = out.removesuffix(".jpg")
    for n, c in enumerate(cs):
        try:
            download(c["thumb"].replace(f"/{WIDTH}px-", "/400px-"), d / f"{stem}__{n:02d}.jpg")
        except Exception as e:
            print("  preview failed:", c["title"], e)
    (d / f"{stem}.txt").write_text("\n".join(f"{n:02d} {c['title']}" for n, c in enumerate(cs)) + "\n", encoding="utf-8")


def main():
    spots = json.loads((IMG_DIR / "photos.json").read_text(encoding="utf-8"))
    credits, report = {}, {}
    for spot in spots:
        if spot.get("file"):
            picked = info(["File:" + spot["file"].removeprefix("File:")])
            pick = picked[0] if picked and ALLOWED.match(picked[0]["license"]) else None
            report[spot["out"]] = []
        else:
            cs = [c for c in candidates(spot) if usable(c)]
            cs.sort(key=lambda c: c["width"] * c["height"], reverse=True)
            report[spot["out"]] = [{k: c[k] for k in ("title", "width", "height", "license", "page")} for c in cs[:15]]
            pick = cs[0] if cs else None
            if PREVIEW_DIR:
                save_previews(spot["out"], cs[:24])
        if not pick:
            print(f"✗ {spot['out']}: 使える写真が見つかりませんでした")
            continue
        download(pick["thumb"], IMG_DIR / spot["out"])
        credits[spot["out"]] = {k: pick[k] for k in ("title", "artist", "license", "license_url", "page")}
        if spot.get("caption"):
            # スポットそのものではない写真（イメージ写真）には、写っている場所を明記します
            credits[spot["out"]]["caption"] = spot["caption"]
        print(f"✓ {spot['out']}: {pick['title']} ({pick['license']}, {pick['artist']})")
        time.sleep(1)
    (IMG_DIR / "credits.json").write_text(json.dumps(credits, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (IMG_DIR / "candidates.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
