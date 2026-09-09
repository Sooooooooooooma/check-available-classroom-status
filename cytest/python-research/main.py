import os
import re
import sys
from urllib.parse import urljoin

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
TARGET_DATE = "2026.8.27"  # 取得対象日 (YYYY.M.D)
GROUP_ID = "19"  # 施設グループID

BASE_URL = f"https://{SUBDOMAIN}.cybozu.com"
LOGIN_URL = f"{BASE_URL}/login"
SCHEDULE_URL = f"{BASE_URL}/o/ag.cgi?page=ScheduleIndex&date=da.{TARGET_DATE}&GID={GROUP_ID}"


def get_cybozu_schedule():
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    })

    # 1. ログインページへアクセス（Cookie・トークン準備）
    login_page = session.get(LOGIN_URL)
    login_page.raise_for_status()

    # 2. ログイン実行
    login_payload = {
        "_username": USERNAME,
        "_password": PASSWORD,
    }
    login_res = session.post(LOGIN_URL, data=login_payload)
    login_res.raise_for_status()

    # ログイン失敗の簡易チェック
    if "login" in login_res.url and "error" in login_res.text:
        raise Exception("ログインに失敗しました。ユーザー名またはパスワードを確認してください。")

    # 3. スケジュールページのHTMLを取得
    schedule_res = session.get(SCHEDULE_URL)
    schedule_res.raise_for_status()

    # 4. HTMLのパース
    soup = BeautifulSoup(schedule_res.text, "html.parser")
    results = []

    for row in soup.find_all("tr"):
        # 施設名セルを特定
        facility_el = row.find("a", href=re.compile(r"ScheduleFacility(Week|Month)")) or row.find("td", class_="dataName")
        if not facility_el:
            continue

        facility_name = re.sub(r"(月予定|週予定|日予定|\s+)", " ", facility_el.get_text()).strip()
        if not facility_name or re.match(r"^\d+（[日月火水木金土]）", facility_name):
            continue  # 日付行を除外

        # 予定リンク（ScheduleView）を抽出
        event_links = row.find_all("a", href=re.compile(r"ScheduleView"))
        for link in event_links:
            href = link.get("href", "")
            full_url = urljoin(BASE_URL, href)

            # イベントIDの抽出
            eid_match = re.search(r"[?&](?:sEID|event)=(\d+)", href, re.IGNORECASE)
            event_id = eid_match.group(1) if eid_match else "-"

            # セル内テキストと時間の抽出
            parent_cell = link.find_parent("td")
            cell_text = re.sub(r"\s+", " ", parent_cell.get_text()).strip() if parent_cell else ""
            
            time_match = re.search(r"(\d{1,2}:\d{2})\s*[-〜~]\s*(\d{1,2}:\d{2})", cell_text)
            start_time = time_match.group(1) if time_match else ""
            end_time = time_match.group(2) if time_match else ""

            results.append({
                "facility": facility_name,
                "event_id": event_id,
                "start": start_time,
                "end": end_time,
                "subject": link.get_text().strip(),
                "text": cell_text,
                "url": full_url,
            })

    # 施設名 + イベントIDで重複排除
    unique_results = list({f"{item['facility']}_{item['event_id']}": item for item in results}.values())
    return unique_results


if __name__ == "__main__":
    events = get_cybozu_schedule()
    for ev in events:
        print(f"[{ev['facility']}] {ev['start']} - {ev['end']} : {ev['subject']} (ID: {ev['event_id']})")