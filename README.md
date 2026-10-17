沖縄に来られるゲストが、楽しく宿泊して、地元の店舗や体験、食文化や自然、世界遺産などを知ることができるコンシェルジュアプリ

## ゲスト向け音声ガイド（`index.html`）

- 右上の **EN / 日本語** で表示と音声ガイドの言語を切り替えられます（選んだ言語は端末に記憶）。`index.html?lang=ja` のように URL で指定することもできます。
- スポット写真は Wikimedia Commons の再配布可能なライセンス（CC BY / CC BY-SA など）の写真のみを使い、写真の右下に作者・ライセンスを表示しています。
- 写真を差し替えるときは `images/photos.json` の `file` を Commons のファイル名に書き換えて push すると、GitHub Actions（スポット写真を取得）が写真とクレジット（`images/credits.json`）を自動で更新します。スポットそのものではないイメージ写真には `caption` で写っている場所を明記してください。

---

## 沖縄・宿泊業ニュース（個人用ダッシュボード）

`dashboard/` に、次の3テーマの最新記事を自動で集めるページがあります。

1. 沖縄観光の実態
2. DX推進のためのAI活用
3. 宿泊業のための補助金施策

情報源：[訪日ラボ](https://honichi.com/)・[HOTEL BANK](https://hotelbank.jp/)・[トラベルボイス](https://www.travelvoice.jp/)・[OCVB（沖縄観光コンベンションビューロー）](https://www.ocvb.or.jp/)・[観光DX（観光庁）](https://kanko-dx.go.jp/)・[リゾテック沖縄](https://resortech-expo.okinawa/)

### しくみ
- GitHub Actions（`.github/workflows/update-news.yml`）が **6時間ごと** に `scripts/fetch_news.py` を実行
- 各サイトの RSS と Google ニュースのサイト内検索から記事を取得し、キーワードでテーマ別に分類
- 結果を `dashboard/data/articles.json` に保存 → ページが読み込んで表示

### 最初にやること
1. このブランチを `main` にマージする（定期実行は `main` 上でしか動きません）
2. Settings → Pages → Source を「Deploy from a branch」、Branch を `main` / `(root)` にして保存
3. Actions タブ → 「ニュース自動更新」→ 「Run workflow」で最初の収集を実行
4. `https://<ユーザー名>.github.io/okinawa-private-guide/dashboard/` を開く

### カスタマイズ
- 分類キーワードやサイトの追加：`scripts/fetch_news.py` の `CATEGORIES` / `SOURCES`
- 更新頻度：`update-news.yml` の `cron`
