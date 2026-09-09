
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
    login_url = f"https://{subdomain}.cybozu.com/login"
 
    with sync_playwright() as p:
        # 初回は headless=False にして実際の画面も目視できるようにする
        browser = p.chromium.launch(headless=False)
        page = browser.new_page()
        page.goto(login_url)
 
        # JSによるフォーム生成を待つ（#login-form-outer の中に要素が入るまで）
        page.wait_for_selector("#login-form-outer input", timeout=15000)
 
        page.screenshot(path="login_screenshot.png", full_page=True)
        with open("rendered_login.html", "w", encoding="utf-8") as f:
            f.write(page.content())
 
        print("スクリーンショットを login_screenshot.png に保存しました。")
        print("レンダリング後のHTMLを rendered_login.html に保存しました。")
 
        # 入力欄らしきinputのname/id/type/placeholderを一覧表示
        inputs = page.eval_on_selector_all(
            "#login-form-outer input",
            """els => els.map(e => ({
                name: e.name,
                id: e.id,
                type: e.type,
                placeholder: e.placeholder
            }))""",
        )
        print("\n=== #login-form-outer 内のinput要素 ===")
        for inp in inputs:
            print(inp)
 
        buttons = page.eval_on_selector_all(
            "#login-form-outer button, #login-form-outer input[type=submit]",
            """els => els.map(e => ({
                tag: e.tagName,
                type: e.type,
                text: e.innerText || e.value
            }))""",
        )
        print("\n=== #login-form-outer 内のボタン要素 ===")
        for b in buttons:
            print(b)
 
        input("\n確認が終わったらEnterキーでブラウザを閉じます...")
        browser.close()
 
 
if __name__ == "__main__":
    main()
 

