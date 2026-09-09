/**
 * Cloudflare Workers エントリーポイント。
 * GET /schedule?groupId=19 で施設予定をJSONで返す。
 *
 * wrangler.toml 側で以下をシークレットとして設定しておくこと:
 *   wrangler secret put CYBOZU_SUBDOMAIN
 *   wrangler secret put CYBOZU_USERNAME
 *   wrangler secret put CYBOZU_PASSWORD
 */

import { CybozuOfficeClient } from "./cybozu-client";

export interface Env {
  CYBOZU_SUBDOMAIN: string;
  CYBOZU_USERNAME: string;
  CYBOZU_PASSWORD: string;
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);

    if (url.pathname !== "/schedule") {
      return new Response("Not Found", { status: 404 });
    }

    const groupId = url.searchParams.get("groupId");
    if (!groupId) {
      return new Response(
        JSON.stringify({ error: "クエリパラメータ groupId が必要です" }),
        { status: 400, headers: { "Content-Type": "application/json" } }
      );
    }

    try {
      const client = new CybozuOfficeClient(env.CYBOZU_SUBDOMAIN);
      await client.login(env.CYBOZU_USERNAME, env.CYBOZU_PASSWORD);
      const events = await client.fetchFacilityEvents(groupId);

      return new Response(JSON.stringify({ events }, null, 2), {
        headers: { "Content-Type": "application/json; charset=utf-8" },
      });
    } catch (err) {
      const message = err instanceof Error ? err.message : "不明なエラー";
      return new Response(JSON.stringify({ error: message }), {
        status: 500,
        headers: { "Content-Type": "application/json; charset=utf-8" },
      });
    }
  },
};
