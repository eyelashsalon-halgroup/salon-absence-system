from playwright.sync_api import sync_playwright
import json
import re

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)
    context = browser.new_context()
    
    with open('session_cookies.json', 'r') as f:
        cookies = json.load(f)
        context.add_cookies(cookies)
    
    page = context.new_page()
    
    # 正しいURL形式
    url = 'https://salonboard.com/KLP/reserve/reserveList/searchDate?date=20260108'
    print(f"アクセス中: {url}")
    page.goto(url, timeout=120000)
    page.wait_for_timeout(5000)
    
    print(f"現在のURL: {page.url}")
    
    reservation_table = None
    for table in page.query_selector_all("table"):
        if table.query_selector("th#comingDate"):
            reservation_table = table
            break
    
    if reservation_table:
        rows = reservation_table.query_selector_all('tbody tr')
        print(f"予約行数: {len(rows)}")
        for row in rows:
            cells = row.query_selector_all('td')
            if len(cells) >= 3:
                status_text = cells[1].text_content().strip()
                if "受付待ち" in status_text:
                    name_elem = cells[2].query_selector("p.wordBreak")
                    customer_name = name_elem.text_content().strip() if name_elem else ""
                    reserve_link = cells[2].query_selector("a[href*='reserveId=']")
                    booking_id = ""
                    if reserve_link:
                        href = reserve_link.get_attribute('href')
                        id_match = re.search(r'reserveId=([A-Z]{2}\d+)', href)
                        if id_match:
                            booking_id = id_match.group(1)
                    print(f"  ✓ {customer_name} ({booking_id})")
    else:
        print("予約テーブルが見つかりません")
    
    browser.close()
