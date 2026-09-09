"""
cybozu.com ログインの挙動を調査するためのデバッグスクリプト。
実際のHTTPレスポンスを保存・表示して、520の原因を切り分ける。

必要な環境変数:
    CYBOZU_SUBDOMAIN
    CYBOZU_USERNAME
    CYBOZU_PASSWORD
"""

import os
import sys

import requests
from bs4 import BeautifulSoup


def require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        print(f"環境変数 {name} が設定されていません。", file=sys.stderr)
        sys.exit(1)
    return value


SUBDOMAIN = require_env("CYBOZU_SUBDOMAIN")
USERNAME = require_env("CYBOZU_USERNAME")
PASSWORD = require_env("CYBOZU_PASSWORD")

BASE_URL = f"https://{SUBDOMAIN}.cybozu.com"
LOGIN_URL = f"{BASE_URL}/login"

session = requests.Session()
session.headers.update(
    {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        )
    }
)

# 1. ログインページを取得して保存 → 実際のフォーム構造を目視確認する
res = session.get(LOGIN_URL)
print("GET /login status:", res.status_code)
with open("login_page.html", "w", encoding="utf-8") as f:
    f.write(res.text)
print("→ login_page.html に保存しました。フォームのaction/inputを確認してください。")

soup = BeautifulSoup(res.text, "html.parser")
form = soup.find("form")
print("\nフォームのaction:", form.get("action") if form else "見つかりません")

payload = {}
for hidden in soup.find_all("input", type="hidden"):
    name = hidden.get("name")
    if name:
        payload[name] = hidden.get("value", "")
print("hiddenフィールド:", payload)

# 2. 実際に見えているtext/password系inputのname属性も確認
for inp in soup.find_all("input"):
    if inp.get("type") in (None, "text", "password", "email"):
        print("  input:", inp.get("name"), inp.get("type"))

# 3. ログインをPOSTしてみて、レスポンスの中身を確認（ステータスで落とさない）
payload["_username"] = USERNAME
payload["_password"] = PASSWORD

login_res = session.post(LOGIN_URL, data=payload, allow_redirects=True)
print("\nPOST /login status:", login_res.status_code)
print("最終URL:", login_res.url)
with open("login_result.html", "w", encoding="utf-8") as f:
    f.write(login_res.text)
print("→ login_result.html に保存しました（レスポンス本文の中身を確認してください）")
