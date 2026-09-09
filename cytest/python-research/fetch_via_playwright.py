"""
Playwrightを使わず、requestsだけでcybozu.comへのログイン〜
施設予定ページ取得までを検証するスクリプト。
これが通れば、エッジ環境(Cloudflare Workers等)でfetch()だけで再現できることになる。

観測されたログインフローの再現:
    1. GET  /login                      → HTML内の REQUEST_TOKEN を取得
    2. POST /api/auth/getToken.json     → トークンの検証/更新 (JSON)
    3. POST /api/auth/login.json        → 実ログイン (JSON: username/password/token)
    4. POST /api/auth/redirect.do       → レガシーCGI(ag.cgi)用セッション確立 (form-urlencoded)
    5. GET  /o/ag.cgi?page=ScheduleIndex&GID=... → 施設予定ページ取得

必要な環境変数:
    CYBOZU_SUBDOMAIN
    CYBOZU_USERNAME
    CYBOZU_PASSWORD
    CYBOZU_GROUP_ID

必要なライブラリ:
    uv pip install requests

実行方法:
    export CYBOZU_SUBDOMAIN=<subdomain>
    export CYBOZU_USERNAME=<username>
    export CYBOZU_PASSWORD=<password>
    export CYBOZU_GROUP_ID=19
    uv run login_via_requests.py
"""

from __future__ import annotations

import json
import os
import re
import sys

import requests


def require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        print(f"環境変数 {name} が設定されていません。", file=sys.stderr)
        sys.exit(1)
    return value


def main() -> None:
    subdomain = require_env("CYBOZU_SUBDOMAIN")
    username = require_env("CYBOZU_USERNAME")
    password = require_env("CYBOZU_PASSWORD")
    group_id = require_env("CYBOZU_GROUP_ID")

    base_url = f"https://{subdomain}.cybozu.com"

    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/151.0.0.0 Safari/537.36"
            )
        }
    )

    # 1. ログイン画面からREQUEST_TOKENを取得
    res = session.get(f"{base_url}/login")
    print("1. GET /login ->", res.status_code)
    match = re.search(r"REQUEST_TOKEN\s*=\s*'([0-9a-f-]+)'", res.text)
    if not match:
        print("REQUEST_TOKENが見つかりませんでした。ログイン画面のHTML構造が変わった可能性があります。")
        sys.exit(1)
    token = match.group(1)
    print("   REQUEST_TOKEN:", token)

    common_headers = {
        "Content-Type": "application/json",
        "Referer": f"{base_url}/login",
    }

    # 2. トークンの検証/更新
    res = session.post(
        f"{base_url}/api/auth/getToken.json",
        params={"_lc": "ja"},
        headers=common_headers,
        data=json.dumps({"__REQUEST_TOKEN__": token}),
    )
    print("\n2. POST /api/auth/getToken.json ->", res.status_code)
    print("   body:", res.text[:500])

    token_for_login = token
    try:
        data = res.json()
        # レスポンスの中に新しいトークンが含まれていれば、それを以後使う
        if isinstance(data, dict):
            for key in ("token", "__REQUEST_TOKEN__", "requestToken"):
                if key in data and data[key]:
                    token_for_login = data[key]
                    break
    except ValueError:
        pass
    print("   使用するトークン:", token_for_login)

    # 3. 実ログイン
    login_payload = {
        "username": username,
        "password": password,
        "keepUsername": False,
        "redirect": "",
        "__REQUEST_TOKEN__": token_for_login,
    }
    res = session.post(
        f"{base_url}/api/auth/login.json",
        params={"_lc": "ja"},
        headers=common_headers,
        data=json.dumps(login_payload),
    )
    print("\n3. POST /api/auth/login.json ->", res.status_code)
    print("   body:", res.text[:500])

    if res.status_code >= 400:
        print("\nログインAPIが失敗しました。ここで処理を中断します。")
        sys.exit(1)

    # 4. レガシーCGI用セッションの確立
    res = session.post(
        f"{base_url}/api/auth/redirect.do",
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Origin": base_url,
            "Referer": f"{base_url}/login",
        },
        data={
            "username": username,
            "password": password,
            "redirect": f"{base_url}/",
        },
    )
    print("\n4. POST /api/auth/redirect.do ->", res.status_code, " 最終URL:", res.url)

    # 5. 施設予定ページ(週表示)を取得
    date_str_url = f"{base_url}/o/ag.cgi?page=ScheduleIndex&GID={group_id}"
    res = session.get(date_str_url)
    print("\n5. GET /o/ag.cgi?page=ScheduleIndex ->", res.status_code, " 長さ:", len(res.text))

    with open("schedule_test.html", "w", encoding="utf-8") as f:
        f.write(res.text)
    print("   -> schedule_test.html に保存しました。")

    if "eventrow" in res.text:
        print("\n   'eventrow' が含まれています。施設予定の取得に成功している可能性が高いです。")
    else:
        print(
            "\n   'eventrow' が見つかりません。ログインが実は成立していないか、"
            "ページ構造が違う可能性があります。schedule_test.html を確認してください。"
        )


if __name__ == "__main__":
    main()