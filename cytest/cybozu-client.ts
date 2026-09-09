/**
 * cybozu Office（クラウド版）にログインし、施設の週間予定を取得するクライアント。
 * Cloudflare Workers上でPlaywright等のブラウザなしに、fetch()とHTMLRewriterだけで動作する。
 *
 * ログインフローは実ブラウザの通信を観測して判明したもの:
 *   1. GET  /login                      → HTML内の REQUEST_TOKEN を取得
 *   2. POST /api/auth/getToken.json     → トークンの検証/更新 (JSON)
 *   3. POST /api/auth/login.json        → 実ログイン (JSON: username/password/token)
 *   4. POST /api/auth/redirect.do       → レガシーCGI(ag.cgi)用セッション確立 (form-urlencoded)
 *   5. GET  /o/ag.cgi?page=ScheduleIndex&GID=... → 施設予定ページ(週表示)取得
 *
 * fetch()は自動でCookieを保持しないため、CookieJarで Set-Cookie を手動管理する。
 */

export interface CybozuFacilityEvent {
  facility: string;
  eventId: string;
  start: Date | null;
  end: Date | null;
  subject: string;
  url: string;
}

/** レスポンスの Set-Cookie を蓄積し、以降のリクエストの Cookie ヘッダーを組み立てる */
class CookieJar {
  private jar = new Map<string, string>();

  updateFrom(headers: Headers): void {
    // Cloudflare Workers の Headers は getSetCookie() で複数のSet-Cookieを個別取得できる
    const getSetCookie = (headers as unknown as { getSetCookie?: () => string[] }).getSetCookie;
    const rawCookies: string[] = typeof getSetCookie === "function"
      ? getSetCookie.call(headers)
      : (headers.get("set-cookie") ? [headers.get("set-cookie") as string] : []);

    for (const raw of rawCookies) {
      const firstPart = raw.split(";")[0];
      const eqIndex = firstPart.indexOf("=");
      if (eqIndex === -1) continue;
      const name = firstPart.slice(0, eqIndex).trim();
      const value = firstPart.slice(eqIndex + 1).trim();
      if (name) this.jar.set(name, value);
    }
  }

  toHeader(): string {
    return Array.from(this.jar.entries())
      .map(([name, value]) => `${name}=${value}`)
      .join("; ");
  }
}

/**
 * cybozuの日時属性をDateに変換する。2つの形式に対応:
 *   - 'dt.2026.8.27.14.0.0' : 日付込み（通常の予定）
 *   - 'tm.10.0.0'           : 時刻のみ（繰り返し予定。日付は data-cb-date から補う）
 * どちらもJST基準の値として解釈し、UTCベースのDateに変換する。
 */
function parseCbDateTime(value: string | null, fallbackDate: string | null): Date | null {
  if (!value) return null;

  if (value.startsWith("dt.")) {
    const parts = value.split(".").slice(1).map(Number);
    if (parts.length < 6 || parts.some((n) => Number.isNaN(n))) return null;
    const [y, mo, d, h, mi, se] = parts;
    // JST(UTC+9) → UTCへ変換。Date.UTCは負の時刻を自動で日付ロールバックしてくれる
    return new Date(Date.UTC(y, mo - 1, d, h - 9, mi, se));
  }

  if (value.startsWith("tm.") && fallbackDate?.startsWith("da.")) {
    const dateParts = fallbackDate.split(".").slice(1).map(Number);
    const timeParts = value.split(".").slice(1).map(Number);
    if (dateParts.length < 3 || timeParts.length < 3) return null;
    if (dateParts.some((n) => Number.isNaN(n)) || timeParts.some((n) => Number.isNaN(n))) return null;
    const [y, mo, d] = dateParts;
    const [h, mi, se] = timeParts;
    return new Date(Date.UTC(y, mo - 1, d, h - 9, mi, se));
  }

  return null;
}

/**
 * 施設週間予定ページ(ScheduleIndex)のHTMLから予定一覧を抽出する。
 * 実際の画面構造:
 *   tr.eventrow                        … 施設1件につき1行
 *     th.facilitycell a                … 施設名
 *     div.dragTarget[data-cb-eid]      … 1件の予定。data-cb-st/et/date に日時情報
 *       a.event[title]                 … 件名(title属性。例: "来客:さとう商事")
 */
export async function parseFacilityEvents(
  html: string,
  baseUrl: string
): Promise<CybozuFacilityEvent[]> {
  const events: CybozuFacilityEvent[] = [];

  let currentFacility = "(施設名不明)";
  let facilityNameBuffer = "";
  let pending: {
    eventId: string;
    cbDate: string | null;
    stRaw: string | null;
    etRaw: string | null;
  } | null = null;

  const rewriter = new HTMLRewriter()
    .on("tr.eventrow", {
      element() {
        currentFacility = "(施設名不明)";
      },
    })
    .on("th.facilitycell a", {
      element(el) {
        facilityNameBuffer = "";
        el.onEndTag(() => {
          const text = facilityNameBuffer.trim();
          if (text) currentFacility = text;
        });
      },
      text(chunk) {
        facilityNameBuffer += chunk.text;
      },
    })
    .on("div.dragTarget[data-cb-eid]", {
      element(el) {
        pending = {
          eventId: el.getAttribute("data-cb-eid") || "",
          cbDate: el.getAttribute("data-cb-date"),
          stRaw: el.getAttribute("data-cb-st"),
          etRaw: el.getAttribute("data-cb-et"),
        };
      },
    })
    .on("a.event", {
      element(el) {
        if (!pending) return;
        const title = el.getAttribute("title") || "";
        const href = el.getAttribute("href") || "";

        events.push({
          facility: currentFacility,
          eventId: pending.eventId,
          start: parseCbDateTime(pending.stRaw, pending.cbDate),
          end: parseCbDateTime(pending.etRaw, pending.cbDate),
          subject: title,
          url: href ? new URL(href, baseUrl).toString() : "",
        });
        pending = null;
      },
    });

  const transformed = rewriter.transform(new Response(html));
  await transformed.text(); // ストリームを最後まで読み切ってハンドラーを発火させる

  return events;
}

export class CybozuOfficeClient {
  private cookies = new CookieJar();
  private baseUrl: string;

  constructor(subdomain: string) {
    this.baseUrl = `https://${subdomain}.cybozu.com`;
  }

  private async request(path: string, init: RequestInit = {}): Promise<Response> {
    const headers = new Headers(init.headers);
    const cookieHeader = this.cookies.toHeader();
    if (cookieHeader) headers.set("Cookie", cookieHeader);

    const res = await fetch(`${this.baseUrl}${path}`, { ...init, headers });
    this.cookies.updateFrom(res.headers);
    return res;
  }

  async login(username: string, password: string): Promise<void> {
    // 1. ログイン画面からREQUEST_TOKENを取得
    const loginPage = await this.request("/login");
    const html = await loginPage.text();
    const match = html.match(/REQUEST_TOKEN\s*=\s*'([0-9a-f-]+)'/);
    if (!match) {
      throw new Error("REQUEST_TOKENが見つかりませんでした。ログイン画面の構造が変わった可能性があります。");
    }
    let token = match[1];

    // 2. トークンの検証/更新
    const tokenRes = await this.request("/api/auth/getToken.json?_lc=ja", {
      method: "POST",
      headers: { "Content-Type": "application/json", Referer: `${this.baseUrl}/login` },
      body: JSON.stringify({ __REQUEST_TOKEN__: token }),
    });
    const tokenBody = await tokenRes.json().catch(() => null) as
      | { result?: { token?: string } }
      | null;
    if (tokenBody?.result?.token) token = tokenBody.result.token;

    // 3. 実ログイン
    const loginRes = await this.request("/api/auth/login.json?_lc=ja", {
      method: "POST",
      headers: { "Content-Type": "application/json", Referer: `${this.baseUrl}/login` },
      body: JSON.stringify({
        username,
        password,
        keepUsername: false,
        redirect: "",
        __REQUEST_TOKEN__: token,
      }),
    });
    if (!loginRes.ok) {
      throw new Error(`ログインAPIが失敗しました (status=${loginRes.status})`);
    }
    const loginBody = await loginRes.json().catch(() => null) as { success?: boolean } | null;
    if (loginBody?.success === false) {
      throw new Error("ログインに失敗しました。ユーザー名またはパスワードを確認してください。");
    }

    // 4. レガシーCGI(ag.cgi)用セッションを確立
    const form = new URLSearchParams({
      username,
      password,
      redirect: `${this.baseUrl}/`,
    });
    await this.request("/api/auth/redirect.do", {
      method: "POST",
      headers: {
        "Content-Type": "application/x-www-form-urlencoded",
        Origin: this.baseUrl,
        Referer: `${this.baseUrl}/login`,
      },
      body: form.toString(),
    });
  }

  async fetchFacilityEvents(groupId: string): Promise<CybozuFacilityEvent[]> {
    const res = await this.request(`/o/ag.cgi?page=ScheduleIndex&GID=${groupId}`);
    const html = await res.text();
    return parseFacilityEvents(html, this.baseUrl);
  }
}
