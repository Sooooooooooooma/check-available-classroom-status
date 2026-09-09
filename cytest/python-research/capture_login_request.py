"""
ログインボタンをクリックした際に、実際にブラウザがどのURL・どんな形式（POSTボディ、
Content-Type、ヘッダー）でリクエストを送っているかを観測するためのスクリプト。

このスクリプトの目的はPlaywrightを使い続けることではなく、
「本物のログインリクエストの形」を1回だけ突き止めて、
それをそのままfetch()で再現できるようにすること。
一度これが分かれば、以降はPlaywrightもブラウザも不要になり、
Cloudflare Workers等のエッジ環境でも動かせるようになる。

必要な環境変数:
    CYBOZU_SUBDOMAIN
    CYBOZU_USERNAME
    CYBOZU_PASSWORD

必要なライブラリ:
    uv pip install playwright
    uv run playwright install chromium

実行方法:
    export CYBOZU_SUBDOMAIN=<subdomain>
    export CYBOZU_USERNAME=<username>
    export CYBOZU_PASSWORD=<password>
    uv run capture_login_request.py
"""

import os
import sys

from playwright.sync_api import sync_playwright


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

    login_url = f"https://{subdomain}.cybozu.com/login"

    captured = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_page()

        def on_request(request):
            # GET以外（POST等）で、静的アセット(css/js/png等)以外の通信だけ記録する
            if request.method != "GET":
                captured.append(request)

        page.on("request", on_request)

        page.goto(login_url)
        page.wait_for_selector('input[name="username"]', timeout=15000)
        page.fill('input[name="username"]', username)
        page.fill('input[name="password"]', password)

        with page.expect_navigation(timeout=15000):
            page.click('input[type="submit"]')

        print("ログイン後のURL:", page.url)

        print(f"\n=== GET以外のリクエスト: {len(captured)}件 ===\n")
        for req in captured:
            print("URL:", req.url)
            print("Method:", req.method)
            print("Headers:", dict(req.headers))
            try:
                post_data = req.post_data
            except Exception:
                post_data = None
            print("PostData:", post_data)
            print("-" * 60)

        input("\n確認が終わったらEnterキーでブラウザを閉じます...")
        browser.close()


if __name__ == "__main__":
    main()
