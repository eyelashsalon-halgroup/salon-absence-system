from playwright.sync_api import sync_playwright
import json, os

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)
    context = browser.new_context()
    page = context.new_page()
    
    # ログイン
    page.goto('https://salonboard.com/login/')
    page.wait_for_timeout(3000)
    page.fill('input[name="userId"]', os.environ.get('SALONBOARD_LOGIN_ID', 'CD18317'))
    page.fill('input[name="password"]', os.environ.get('SALONBOARD_LOGIN_PASSWORD', 'Ne8T2Hhi!'))
    page.keyboard.press('Enter')
    page.wait_for_timeout(5000)
    
    # 予約ページへ
    page.goto('https://salonboard.com/KLP/reserve/reserveList/searchDate?date=20251227')
    page.wait_for_timeout(3000)
    
    print(f"URL: {page.url}")
    print(f"Title: {page.title()}")
    
    for table in page.query_selector_all('table'):
        if table.query_selector('th#comingDate'):
            rows = table.query_selector_all('tbody tr')
            print(f"行数: {len(rows)}")
            for row in rows[:2]:
                html = row.inner_html()[:500]
                print(f"HTML: {html}")
                print("---")
    
    # クッキー保存
    cookies = context.cookies()
    with open('session_cookies.json', 'w') as f:
        json.dump(cookies, f)
    print("クッキー保存完了")
    
    browser.close()
