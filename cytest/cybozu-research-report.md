# サイボウズ Office 施設予定 取得方式 技術調査レポート

**目的**: サイボウズ Office（クラウド版）から会議室などの施設予約データをプログラムで取得し、最終的に Cloudflare Workers 等のエッジ環境で定期実行できるようにする。

**本レポートの位置づけ**: 調査は完了し、動作する実装まで到達している。本ドキュメントは「なぜその方式になったのか」の経緯と「どうやって自分で調べ直すか」の手順を含む。仕様変更で動かなくなったとき、このレポートの手順をなぞれば自力で再調査できることを意図している。

---

## 0. 最初に読むべき要約

| 項目 | 結論 |
|---|---|
| 公式 REST API | **存在しない**。サイボウズ Office にはない（あるのは上位製品の Garoon / kintone） |
| iCalendar 出力 | **施設には使えない**。本人の予定のみ |
| 採用した方式 | ログイン API を叩いてセッションを取得 → レガシー CGI 画面（`ag.cgi`）の HTML をパース |
| ブラウザ自動化 | **不要**（調査時のみ使用）。最終実装は `fetch` のみで動作 |
| 最終成果物 | `cybozu-client.ts` / `worker.ts`（Cloudflare Workers 対応・型チェック通過済み） |

**注意事項（最重要）**

- これは公式サポートのない非公式手段である。**サイボウズ側の画面構造やログイン実装が変われば即座に壊れる**。壊れることを前提に、後述の「再調査手順」を残してある。
- 認証情報は**絶対にコードに直書きしない**。環境変数・シークレットで管理すること。
- 短時間に大量アクセスするとサービス側に負荷をかける。取得間隔は最低でも数分以上空けること。
- 実運用に入れる前に、対象環境の管理者に許可を取ること。

---

## 1. 調査の出発点と、最初に潰した選択肢

### 1-1. 公式ドキュメントの確認結果

サイボウズ Office のマニュアルには「iCalendar 形式に出力するための準備」という機能がある。しかし仕様を読むと以下の制約があった。

- iCalendar URL は**ユーザーごとに 1 つ**発行される
- 出力されるのは**本人が参加者として登録されている予定のみ**
- **施設（会議室）の予約は対象外**
- URL を知っていれば未ログインでも閲覧できてしまうため、取り扱いに注意が必要

今回やりたいのは「施設の予約状況の取得」なので、**この機能では要件を満たせない**と判断。

### 1-2. 検討した代替案と評価

| 案 | 内容 | 評価 |
|---|---|---|
| A. CSV エクスポート | 画面から手動でダウンロード | 自動化できないので却下 |
| B. ダミーユーザー方式 | 「会議室A」というユーザーを作り、施設予約と同時に参加者登録。そのユーザーの iCalendar URL を使う | 運用ルールの徹底が必要／ライセンス費用が発生／登録漏れで破綻するので却下 |
| C. REST API | `/o/api/v1/schedule/events` を叩く | **後述の通り存在しなかった** |
| D. 画面スクレイピング | ログインして CGI 画面の HTML を解析 | **採用** |

### 1-3. 罠: 存在しない REST API

調査の初期段階で「サイボウズ Office には REST API がある」という情報に基づき、以下を試した。

```javascript
// ブラウザのコンソールで実行
const res = await fetch("/o/api/v1/schedule/facilities", {
  headers: { "X-Requested-With": "XMLHttpRequest" },
});
```

結果:

```
GET https://<subdomain>.cybozu.com/o/api/v1/schedule/facilities 404 (Not Found)
Uncaught (in promise) SyntaxError: Unexpected token '<', "<!DOCTYPE "... is not valid JSON
```

**404 が返り、HTML（エラーページ）が返ってきた**ため `res.json()` が構文エラーになっている。

原因: `/o/api/v1/...` という REST API は**上位製品の Garoon の仕様**であり、サイボウズ Office には存在しない。サイボウズ Office は `ag.cgi` という**レガシーな CGI アーキテクチャ**で動作している。

> **後輩へ**: AI や記事の情報は製品を取り違えていることがある。「サイボウズ Office」「Garoon」「kintone」は別製品で API 仕様も別。404 が返ったら、まずエンドポイントがその製品に本当に存在するかを疑うこと。レスポンスが JSON でなく HTML なら、それは「API ではなく普通の Web ページ（かエラーページ）を叩いている」サイン。

---

## 2. データ構造の解析（ブラウザコンソールでの探索）

REST API がないと分かったので、実際の画面の HTML から取る方針に切り替えた。

### 2-1. 探索の手順

1. ブラウザでサイボウズ Office にログインする
2. 施設のスケジュール画面を開き、URL を確認する
   例: `/o/ag.cgi?page=ScheduleIndex&date=da.2026.8.27&GID=19`
   - `page=ScheduleIndex` … 画面の種類
   - `date=da.YYYY.M.D` … 表示日付
   - `GID=19` … 施設グループ ID
3. F12 で開発者ツールを開き、Console タブで以下を実行して構造を探る

```javascript
(async () => {
  const res = await fetch("/o/ag.cgi?page=ScheduleIndex&date=da.2026.8.27&GID=19");
  const text = await res.text();
  const doc = new DOMParser().parseFromString(text, "text/html");

  const results = [];
  doc.querySelectorAll("tr").forEach((row) => {
    row.querySelectorAll('a[href*="ScheduleView"]').forEach((link) => {
      results.push({
        予定名: link.textContent.trim(),
        URL: link.href,
      });
    });
  });
  console.table(results);
})();
```

ログイン済みブラウザのコンソールで実行すると、**Cookie がそのまま使われる**ため認証を書かずに試せる。構造探索の初手として非常に有効。

### 2-2. この段階で判明したこと

- 予定の詳細リンクは `ag.cgi?page=ScheduleView&...&sEID=11&...` の形式
- **イベント ID のパラメータ名は `sEID`**（一般的な `event` や `id` ではない）
- 施設名と予定が同じ行に並んでいる

### 2-3. 落とし穴: 重複行

初期のスクリプトでは同じ予定が複数回取得された。原因は、日付ヘッダー行と施設行の両方が `<tr>` として引っかかっていたため。**「`<tr>` を全部舐める」という雑なセレクタは重複を生む**。後述の最終版では `tr.eventrow` という具体的なクラスを指定して解決している。

---

## 3. ログイン処理の攻略（本調査の山場）

コンソールから手動で叩けることは分かったが、サーバー側で自動実行するにはプログラムからログインする必要がある。ここが最も難航した。

### 3-1. 失敗 1: 素朴な form POST → HTTP 520

まず「ログインページの HTML を取得し、hidden フィールドを拾って `_username` / `_password` を POST する」という定番の方法を試した。

```python
payload["_username"] = USERNAME
payload["_password"] = PASSWORD
res = session.post(LOGIN_URL, data=payload)
```

結果:

```
requests.exceptions.HTTPError: 520 Server Error: 520 for url: https://<subdomain>.cybozu.com/login
```

**520 は Cloudflare が「オリジンサーバーから不正・空のレスポンスが返った」ときに出すエラー**。この時点では原因が特定できないため、次の切り分けに進んだ。

### 3-2. 切り分け: レスポンスを保存して目視する

`raise_for_status()` は例外を投げてしまい中身が見えないので、**ステータスで落とさずレスポンス本文をファイルに保存する**デバッグスクリプトを書いた。これが突破口になった。

```python
res = session.get(LOGIN_URL)
with open("login_page.html", "w", encoding="utf-8") as f:
    f.write(res.text)

soup = BeautifulSoup(res.text, "html.parser")
for inp in soup.find_all("input"):
    print("input:", inp.get("name"), inp.get("type"))
```

> **後輩へ**: これは汎用的に使えるテクニック。うまくいかないときは「エラーを見る」のではなく「**サーバーが実際に何を返したかを保存して自分の目で見る**」。推測でコードを書き換えるより圧倒的に速い。

### 3-3. 判明した原因 1: フォームが JS で動的生成されている

保存した `login_page.html` を開いたところ、**`<input>` が 1 つも存在しなかった**。あったのは空の箱だけ。

```html
<div id="login-form-outer" class="login-form-outer">
</div>
...
<script src="https://static.cybozu.com/ROOT/slash_.../js/compiled/login.js"></script>
<script>
  cybozu.data.REQUEST_TOKEN = '28ede3db-736b-4336-a92d-8bc4f718a0a6';
</script>
```

つまり、**ログインフォームは `login.js` が実行されて初めて DOM に生成される**。`requests` は JavaScript を実行しないので、`_username` という名前の input は最初から存在しなかった。

POST 後のレスポンス（`login_result.html`）にも、はっきりと理由が書かれていた。

```html
<h3 class="error-title-cybozu">不正なリクエストです。</h3>
<li><strong>Code:</strong> CB_IL02</li>
```

サーバーが期待していないパラメータを送ったため弾かれていた、というのが 520 / CB_IL02 の正体。

**同時に発見した重要な手がかり**: HTML 内に `cybozu.data.REQUEST_TOKEN = '...'` という UUID 形式の CSRF トークンが埋め込まれている。これは後で必ず使うことになる。

### 3-4. Playwright を「調査道具」として投入する

JS を実行しないと本当のフォームが見えないので、**Playwright（ブラウザ自動化）を一時的に導入**した。

ここで方針として重要なのは、**Playwright を最終形にしない**こと。エッジ環境ではブラウザは動かせない。あくまで「本物の通信を観測するための道具」として使い、観測が終わったら捨てる。

まずレンダリング後の本物の input 名を調べた。

```python
page.goto(login_url)
page.wait_for_selector("#login-form-outer input", timeout=15000)

inputs = page.eval_on_selector_all(
    "#login-form-outer input",
    """els => els.map(e => ({ name: e.name, id: e.id, type: e.type, placeholder: e.placeholder }))""",
)
```

結果:

```
{'name': 'username', 'id': 'username-:0-text',  'type': 'text',     'placeholder': 'ログイン名'}
{'name': 'password', 'id': 'password-:1-text',  'type': 'password', 'placeholder': 'パスワード'}
{'name': '',         'id': 'input-rememberMe-slash', 'type': 'checkbox'}
{'name': '',         'id': '', 'type': 'submit'}
{'name': 'redirect', 'id': '', 'type': 'hidden'}
```

**`_username` ではなく `username` が正しい名前だった**（アンダースコアなし）。

### 3-5. 決定打: 実際の通信をキャプチャする

input 名が分かってもまだ足りない。フォームがどこへ、どんな Content-Type で送信しているかが不明だからだ。そこで **Playwright のリクエストイベントを監視し、ログインボタンを押した瞬間の全通信を記録**した。

```python
captured = []
page.on("request", lambda req: captured.append(req) if req.method != "GET" else None)

page.fill('input[name="username"]', username)
page.fill('input[name="password"]', password)
with page.expect_navigation(timeout=15000):
    page.click('input[type="submit"]')

for req in captured:
    print("URL:", req.url)
    print("Headers:", dict(req.headers))
    print("PostData:", req.post_data)
```

これで**ログインの全貌が判明**した。単一の form POST ではなく、**4 段階の API 呼び出し**だった。

| # | エンドポイント | Content-Type | ボディ |
|---|---|---|---|
| 1 | `GET /login` | - | HTML 内の `REQUEST_TOKEN` を取得 |
| 2 | `POST /api/auth/getToken.json?_lc=ja` | `application/json` | `{"__REQUEST_TOKEN__":"<uuid>"}` |
| 3 | `POST /api/auth/login.json?_lc=ja` | `application/json` | `{"username":"...","password":"...","keepUsername":false,"redirect":"","__REQUEST_TOKEN__":"<uuid>"}` |
| 4 | `POST /api/auth/redirect.do` | `application/x-www-form-urlencoded` | `username=...&password=...&redirect=https%3A%2F%2F<subdomain>.cybozu.com%2F` |

**なぜ 4 段階なのか（推測を含む）**

- 2 と 3 は新しい認証基盤（JSON API）。CSRF トークンを検証してからログインさせている
- 4 の `redirect.do` が重要で、これが**レガシー CGI（`ag.cgi`）側で通用するセッション Cookie を確立している**と考えられる。3 だけでは `ag.cgi` にアクセスできない可能性が高い

> **後輩へ**: この「実通信のキャプチャ」が本調査で最も価値のあった手順。ブラウザの Network タブでも同じことができる（Preserve log を ON にしてログイン → `login` や `auth` で絞り込み → Payload / Headers を見る）。**推測でパラメータを組み立てるのではなく、本物を観測してそのまま真似る**。

### 3-6. 検証: Playwright なしで再現する

観測した 4 段階を `requests` でそのまま実装し、ブラウザなしで通ることを確認した。

```
1. GET /login -> 200
   REQUEST_TOKEN: 212e3c6b-51cf-400e-af03-5164cc03e59b
2. POST /api/auth/getToken.json -> 200
   {"result": {"token": "212e3c6b-..."}, "success": true}
3. POST /api/auth/login.json -> 200
   {"result": {"redirect": "https://<subdomain>.cybozu.com/",
               "requestToken": "bd1909f6-..."}, "success": true}
4. POST /api/auth/redirect.do -> 200  最終URL: https://<subdomain>.cybozu.com/
5. GET /o/ag.cgi?page=ScheduleIndex -> 200  長さ: 63291
   'eventrow' が含まれています。
```

**この時点で Playwright は不要になった**。以降の実装はすべて素の HTTP で完結する。

---

## 4. HTML 構造の解析（2 度目の壁）

ログインは通ったが、パース結果が **0 件**だった。ここでも「レスポンスを保存して目視する」を実践した。

### 4-1. 誤っていた前提

当初は「日ごとの表で、`<tr>` 1 行 = 予定 1 件」だと想定していた。実際は**週表示のテーブル**で、構造がまったく違った。

- **`<tr class="eventrow">` 1 行 = 施設 1 件**
- その行の中に **7 日分の `<td class="eventcell">` が横に並ぶ**
- 予定は各セルの中の `div.dragTarget` にある

### 4-2. 実際の HTML（重要部分の抜粋）

```html
<tr class="eventrow" valign="top" style="height:3em">
  <th class="facilitycell">
    <div class="scheduleFirstCellItem">
      <img class="profileImage" src="..." >
      <a href="ag.cgi?page=ScheduleFacility&UID=21&GID=19&...">第一会議室</a>
    </div>
    <div class="linkfacilitymonth">
      <a href="ag.cgi?page=ScheduleUserMonth&UID=21&...">月予定</a>
    </div>
  </th>
  <td class="eventcell" onclick="...">
    <div class="dropArea" data-cb-date="da.2026.8.27" data-cb-uid="21">
      <div class="dragTarget dnd-eventdiv-draggable"
           data-cb-date="da.2026.8.27"
           data-cb-uid="21"
           data-cb-st="dt.2026.8.27.14.0.0"
           data-cb-et="dt.2026.8.27.15.0.0"
           data-cb-eid="11"
           draggable="true">
        <div class="eventLink ...">
          <div class="eventInner">
            <span class="eventDateTime">14:00-15:00&nbsp;</span>
            <span class="eventDetail">
              <a class="event"
                 href="ag.cgi?page=ScheduleView&UID=21&GID=19&...&sEID=11&CP=sg"
                 title="来客:さとう商事">
                <span class="scheduleEventMenu">来客</span>さとう商事
              </a>
            </span>
          </div>
        </div>
      </div>
    </div>
  </td>
  <!-- 以降、8/28, 8/29 ... と 7 日分の td が続く -->
</tr>
```

### 4-3. 幸運な発見: `data-cb-*` 属性

**表示テキストを正規表現で頑張ってパースする必要はなかった**。ドラッグ＆ドロップ機能のために、必要な情報がすべて `data-` 属性として構造化されて埋め込まれていた。

| 属性 | 意味 | 例 |
|---|---|---|
| `data-cb-eid` | イベント ID | `11` |
| `data-cb-uid` | 施設（ユーザー）ID | `21` |
| `data-cb-date` | 日付 | `da.2026.8.27` |
| `data-cb-st` | 開始日時 | `dt.2026.8.27.14.0.0` |
| `data-cb-et` | 終了日時 | `dt.2026.8.27.15.0.0` |

件名は `a.event` の **`title` 属性**に `"来客:さとう商事"`（`メニュー:件名` 形式）として入っている。

> **後輩へ**: スクレイピングでは「表示テキストより属性を優先して探す」。表示は書式変更で壊れやすいが、機能のために埋め込まれた `data-` 属性は比較的安定している。DevTools の Elements タブで対象要素を右クリック → Inspect し、属性一覧を必ず確認すること。

### 4-4. 落とし穴: 日時フォーマットが 2 種類ある

パースを実装して 2 件取得できたが、**1 件だけ開始・終了時刻が `None` になった**。

該当箇所を確認すると:

```html
<!-- 通常の予定 -->
data-cb-st="dt.2026.8.27.14.0.0"

<!-- 繰り返し予定 -->
data-cb-st="tm.10.0.0"
```

**繰り返し予定は `tm.` 接頭辞で時刻のみ**を持ち、日付は同じ要素の `data-cb-date="da.2026.8.27"` から補完する必要があった。

3 つの接頭辞の意味:

| 接頭辞 | 形式 | 意味 |
|---|---|---|
| `da.` | `da.YYYY.M.D` | 日付のみ |
| `dt.` | `dt.YYYY.M.D.H.MI.S` | 日時 |
| `tm.` | `tm.H.MI.S` | 時刻のみ（繰り返し予定で使用） |

**この 1 件を見逃していたら、繰り返し予定だけ静かに欠損する**という発見しづらいバグになっていた。テストデータには必ず「通常の予定」と「繰り返し予定」の両方を含めること。

### 4-5. 修正後の確認結果

```
=== 週間予定: 2件 ===
[第一会議室] 08/27 14:00-15:00 来客:さとう商事 (event_id=11)
[第二会議室] 08/27 10:00-11:00 会議:営業会議 (event_id=19)
```

両方とも時刻付きで正しく取得できた。

---

## 5. 最終実装（Cloudflare Workers 向け TypeScript）

### 5-1. 構成

| ファイル | 役割 |
|---|---|
| `cybozu-client.ts` | ログイン処理・HTML パース・型定義（ロジック本体） |
| `worker.ts` | Workers のエントリーポイント（`GET /schedule?groupId=19` で JSON 返却） |

### 5-2. エッジ環境ならではの実装ポイント

**(1) Cookie を手動管理する**

ブラウザや `requests.Session` と違い、**Workers の `fetch` は Cookie を自動保持しない**。`Set-Cookie` を自分で読み取り、次のリクエストの `Cookie` ヘッダーに詰め直す `CookieJar` クラスを実装している。

複数の `Set-Cookie` を取るには `Headers.getSetCookie()` を使う（`headers.get("set-cookie")` だと結合されて壊れることがある）。

```typescript
const getSetCookie = (headers as unknown as { getSetCookie?: () => string[] }).getSetCookie;
const rawCookies: string[] = typeof getSetCookie === "function"
  ? getSetCookie.call(headers)
  : (headers.get("set-cookie") ? [headers.get("set-cookie") as string] : []);
```

**(2) HTMLRewriter を使う**

Workers には Node.js の `cheerio` や `jsdom` は基本的に持ち込みたくない（サイズ・互換性の問題）。代わりに **Cloudflare 組み込みの `HTMLRewriter`** を使う。CSS セレクタでハンドラを登録するストリーミングパーサーで、追加依存なしで動く。

注意点として、**`transform()` した Response は最後まで読み切らないとハンドラが発火しない**。

```typescript
const transformed = rewriter.transform(new Response(html));
await transformed.text();  // これを忘れると events が空のままになる
```

**(3) タイムゾーンの扱い**

Workers のランタイムは UTC で動く。`data-cb-*` の値は JST 前提なので、`Date.UTC()` で 9 時間引いて変換している。

```typescript
return new Date(Date.UTC(y, mo - 1, d, h - 9, mi, se));
```

`h - 9` が負になっても `Date.UTC` が自動で前日にロールバックしてくれるため、条件分岐は不要。

### 5-3. デプロイ手順

```bash
# 1. プロジェクト作成
npm create cloudflare@latest cybozu-worker
cd cybozu-worker

# 2. cybozu-client.ts / worker.ts を src/ に配置

# 3. シークレット設定（コードに直書きしないこと）
npx wrangler secret put CYBOZU_SUBDOMAIN
npx wrangler secret put CYBOZU_USERNAME
npx wrangler secret put CYBOZU_PASSWORD

# 4. ローカル起動
npx wrangler dev
# → http://localhost:8787/schedule?groupId=19

# 5. デプロイ
npx wrangler deploy
```

型チェックは以下で通ることを確認済み。

```bash
npx tsc --noEmit
```

---

## 6. テスト方法

### 6-1. 段階的に切り分けるテスト戦略

一気に通そうとせず、**必ず下から順に確認する**。上の層で失敗したとき、どこが原因か即座に分かる。

| 段階 | 確認内容 | 成功の判定基準 |
|---|---|---|
| L1 | ログインページが取得できるか | `GET /login` が 200 |
| L2 | REQUEST_TOKEN が抽出できるか | UUID 形式の文字列が取れる |
| L3 | ログイン API が成功するか | `login.json` が `"success": true` |
| L4 | CGI セッションが有効か | `ag.cgi` の HTML に `eventrow` が含まれる |
| L5 | パースが正しいか | 予定件数 > 0、かつ開始・終了時刻が `null` でない |

### 6-2. パース単体のテスト（推奨）

**毎回ログインしてテストするのは遅く、サーバーにも負荷をかける。** 一度取得した HTML をファイルに保存し、それに対してパース関数を実行するテストを書くこと。

```bash
# 1. 実際の HTML を一度だけ取得して保存
#    （login_via_requests.py が schedule_test.html を吐く）

# 2. 以降はそのファイルでパースだけを繰り返しテスト
```

Python 側での確認例:

```python
from fetch_via_playwright import parse_facility_events

with open("schedule_test.html", encoding="utf-8") as f:
    html = f.read()

events = parse_facility_events(html, "https://<subdomain>.cybozu.com")
print(len(events), "件")
for e in events:
    print(e.facility, e.start, e.end, e.subject, e.event_id)
```

TypeScript 側では、保存した HTML を読み込んで `parseFacilityEvents()` に渡すテストを `vitest` 等で書くとよい。`HTMLRewriter` は `wrangler dev` / `vitest-pool-workers` 環境でのみ動く点に注意。

### 6-3. テストデータに必ず含めるべきケース

検証環境で以下の予定を**手動で作成してから**テストすること。1 種類だけだとバグを見逃す。

- [ ] 通常の単発予定（`dt.` 形式になる）
- [ ] **繰り返し予定**（`tm.` 形式になる。4-4 のバグの原因）
- [ ] 終日予定（時刻情報がどうなるか未検証。要確認）
- [ ] 同一施設に同じ日で複数件の予定
- [ ] 予定が 1 件もない施設（空行が正しくスキップされるか）
- [ ] 日をまたぐ予定（未検証。要確認）
- [ ] 施設が 3 件以上あるグループ

### 6-4. 回帰テストの考え方

サイボウズ側の仕様変更で壊れることが前提なので、**「壊れたことに気づける」仕組み**を入れること。

- 取得件数が 0 件だったら通知を飛ばす（正常に 0 件の場合と区別が必要なら、施設行の検出数も見る）
- `start` や `end` が `null` の予定があったら警告ログを出す（新しい日時フォーマットの出現を検知できる）

---

## 7. トラブルシューティング表

| 症状 | 考えられる原因 | 対処 |
|---|---|---|
| HTTP 520 | 送信パラメータがサーバーの想定と違う | レスポンス本文を保存して確認。3-2 の手順へ |
| `不正なリクエストです` `CB_IL02` | CSRF トークン不正、またはパラメータ名の誤り | REQUEST_TOKEN を取り直す。3-5 の 4 段階を再確認 |
| `Unexpected token '<' ... is not valid JSON` | JSON を期待したが HTML（エラーページ）が返っている | エンドポイントが存在するか確認。1-3 参照 |
| ログインは通るが `ag.cgi` が取れない | `redirect.do`（4 段階目）を飛ばしている | CGI 用セッションはこれで確立される |
| 取得 0 件 | セレクタが実構造と不一致 | HTML を保存し `eventrow` の有無を確認。4 章参照 |
| 一部の予定だけ時刻が `null` | 繰り返し予定の `tm.` 形式 | 4-4 参照 |
| Workers で 0 件（ローカルでは動く） | `transform()` の結果を読み切っていない | `await transformed.text()` を追加 |
| Workers で Cookie が効かない | `fetch` は Cookie を自動保持しない | `CookieJar` で手動管理。5-2 参照 |
| 時刻が 9 時間ずれる | タイムゾーン未考慮 | JST → UTC 変換を確認 |

---

## 8. セキュリティ上の注意

**本調査中に、認証情報がチャットログに平文で残る事故が発生した。同じ失敗をしないこと。**

- **パスワードをコードやチャット、Issue、Slack に貼らない**。一度貼ったら漏洩したものとして扱い、速やかにローテーションする
- 認証情報は環境変数（ローカル）／`wrangler secret`（Workers）で管理する
- `.env` は必ず `.gitignore` に入れる。**コミット履歴に一度入ると消すのは非常に面倒**
- 専用アカウントを作り、必要最小限の権限のみ付与する（施設の閲覧権限だけで足りるはず）
- 2 要素認証が有効なアカウントでは、この方式のログインは通らない。運用アカウントの設計時に考慮すること
- 取得したデータに個人名（参加者名など）が含まれる。取り扱いとログ出力に注意する

---

## 9. 未検証事項・今後の課題

**後輩へのタスク候補**。調査はここまでで、以下は手つかず。

### 9-1. 機能面

- [ ] **複数週の取得**: 現在は「今日を含む 1 週間」のみ。`date=da.YYYY.M.D` を変えてループする実装が必要
- [ ] **終日予定・日跨ぎ予定**の挙動確認（`data-cb-st` がどうなるか未検証）
- [ ] **施設グループ ID の動的取得**: 現在は `GID=19` をハードコード。グループ一覧を取得する画面を探す
- [ ] **参加者情報の取得**: 一覧画面には含まれない。`page=ScheduleView&sEID=...` の詳細画面を叩けば取れるはず
- [ ] 件名の分割（`"来客:さとう商事"` → メニュー `来客` / 件名 `さとう商事`）

### 9-2. 運用面

- [ ] **Cron Triggers での定期実行**（`wrangler.toml` の `[triggers]` に設定）
- [ ] **KV / D1 へのキャッシュ**: 毎リクエストでログインするのは重いしサーバーに負荷をかける。セッション Cookie か取得結果をキャッシュする
- [ ] **Google カレンダーへの同期**: Python 版で試作済み（`sync_cybozu_to_gcal.py`）。イベントに `extendedProperties.private.cybozu_event_id` を持たせて対応付け、新規作成／更新／削除を判定する設計。Workers に移す場合は OAuth ではなくサービスアカウント + JWT が現実的
- [ ] エラー時の通知（Slack / Discord Webhook など）
- [ ] レート制限・リトライ処理

### 9-3. 設計上の検討事項

- サイボウズ側の仕様変更で壊れる前提なので、**パース部分を差し替えやすい構造**にしておくこと（現状の `parseFacilityEvents` は独立関数なので比較的差し替えやすい）
- 本当にこの方式でよいか、定期的に公式の API 提供状況を確認すること

---

## 10. 成果物一覧

| ファイル | 用途 | 備考 |
|---|---|---|
| `cybozu-client.ts` | **本番用**ロジック本体 | Workers 対応・型チェック通過済み |
| `worker.ts` | **本番用**エントリーポイント | `GET /schedule?groupId=19` |
| `login_via_requests.py` | 検証用 | Playwright なしでログインが通るかの確認 |
| `fetch_via_playwright.py` | 調査用 | 実ブラウザでの取得。構造確認に使用 |
| `capture_login_request.py` | 調査用 | 実通信のキャプチャ。仕様変更時に再実行する |
| `inspect_login_form.py` | 調査用 | レンダリング後のフォーム構造確認 |
| `debug_cybozu_login.py` | 調査用 | レスポンス保存による切り分け |
| `sync_cybozu_to_gcal.py` | 試作 | Google カレンダー同期（Python 版・未完成） |

**仕様変更で壊れたときは、`capture_login_request.py` と `inspect_login_form.py` を再実行するところから始めること。** 調査用スクリプトを残してあるのはそのため。

---

## 付録: 本調査から学べる汎用テクニック

このプロジェクト固有の話を離れて、他の案件でも使える手法をまとめる。

1. **エラーメッセージではなくレスポンス本文を見る**
   `raise_for_status()` を外し、`res.text` をファイルに保存して目視する。原因特定が劇的に速くなる。

2. **JS 生成の UI は静的 HTML には存在しない**
   `requests` で取った HTML に要素がないなら、それは JS が作っている。ブラウザ自動化で「レンダリング後」を見る。

3. **推測せず、本物の通信を観測する**
   DevTools の Network タブ、または Playwright の `page.on("request")`。パラメータ名や Content-Type を当てにいくのは時間の無駄。

4. **ブラウザ自動化は「調査道具」であって「最終形」ではない**
   観測 → 素の HTTP で再現 → ブラウザを捨てる。この順序を意識すると、重いランタイムに依存しない実装に着地できる。

5. **表示テキストより `data-*` 属性を探す**
   機能のために埋め込まれた属性は構造化されており、書式変更に強い。

6. **同じ意味のデータに複数フォーマットがあることを疑う**
   `dt.` と `tm.` のように、条件によって形式が変わることがある。テストデータのバリエーションを増やして炙り出す。

7. **製品名を取り違えた情報に注意する**
   Office / Garoon / kintone のように、同じベンダーの別製品の仕様が混ざった情報が流通している。404 が返ったらまずそれを疑う。
