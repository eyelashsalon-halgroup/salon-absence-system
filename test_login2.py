from playwright.sync_api import sync_playwright
import os

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)
    page = browser.new_page()
    
    page.goto('https://salonboard.com/login/')
    page.wait_for_timeout(3000)
    
    page.fill('input[name="userId"]', os.environ.get('SALONBOARD_LOGIN_ID', 'CD18317'))
    page.fill('input[name="password"]', os.environ.get('SALONBOARD_LOGIN_PASSWORD', 'Ne8T2Hhi!'))
    print("ID/PW入力完了")
    
    # ログインボタンをクリック
    btn = page.query_selector('a.common-CNCcommon__primaryBtn')
    if btn:
        print("ボタン発見、クリック")
        btn.click()
    else:
        print("ボタン未発見、Enterで試行")
        page.keyboard.press('Enter')
    
    page.wait_for_timeout(10000)
    print(f"URL: {page.url}")
    
    if '/KLP/' in page.url:
        print("ログイン成功!")
        # 予約ページへ
        page.goto('https://salonboard.com/KLP/reserve/reserveList/searchDate?date=20251227')
        page.wait_for_timeout(3000)
        
        for table in page.query_selector_all('table'):
            if table.query_selector('th#comingDate'):
                rows = table.query_selector_all('tbody tr')
                print(f"予約数: {len(rows)}")
                for row in rows[:2]:
                    cells = row.query_selector_all('td')
                    link = row.query_selector('a[href*="reserveId="]')
                    print(f"cells={len(cells)}, link={link is not None}")
    
    input("確認後Enter...")
    browser.close()
