import json, re, os
from datetime import datetime, timedelta, timezone
from playwright.sync_api import sync_playwright

JST = timezone(timedelta(hours=9))
today = datetime.now(JST)

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)
    context = browser.new_context()
    
    page = context.new_page()
    
    # ログイン
    page.goto('https://salonboard.com/login/', timeout=60000)
    page.wait_for_timeout(3000)
    page.fill('input[name="userId"]', 'CD18317')
    page.fill('input[name="password"]', 'Ne8T2Hhi!')
    btn = page.query_selector('a.common-CNCcommon__primaryBtn')
    if btn:
        btn.click()
    
    for i in range(30):
        page.wait_for_timeout(1000)
        if '/KLP/' in page.url:
            print("ログイン成功")
            break
    
    # 予約ページへ
    url = f'https://salonboard.com/KLP/reserve/reserveList/searchDate?date={today.strftime("%Y%m%d")}'
    page.goto(url, timeout=60000)
    page.wait_for_timeout(2000)
    
    print(f"URL: {page.url}")
    
    # v4と同じロジック
    reservation_table = None
    for table in page.query_selector_all("table"):
        if table.query_selector("th#comingDate"):
            reservation_table = table
            break
    
    if not reservation_table:
        print("テーブルなし")
    else:
        rows = reservation_table.query_selector_all('tbody tr')
        print(f"行数: {len(rows)}")
        
        for i, row in enumerate(rows[:5]):
            cells = row.query_selector_all('td')
            link = row.query_selector('a[href*="reserveId="]')
            print(f"row[{i}]: cells={len(cells)}, link={link is not None}")
            
            if len(cells) >= 2:
                print(f"  cell0: [{cells[0].inner_text()[:30]}]")
                print(f"  cell1: [{cells[1].inner_text()[:30]}]")
            
            if link:
                href = link.get_attribute('href')
                match = re.search(r'reserveId=(\d+)', href)
                if match:
                    print(f"  booking_id: {match.group(1)}")
            else:
                all_a = row.query_selector_all('a')
                print(f"  リンクなし、全a数: {len(all_a)}")
                for a in all_a[:2]:
                    print(f"    href: {(a.get_attribute('href') or '')[:60]}")
    
    browser.close()
