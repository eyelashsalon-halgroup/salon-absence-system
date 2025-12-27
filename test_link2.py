from playwright.sync_api import sync_playwright
import json

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)
    context = browser.new_context()
    try:
        with open('session_cookies.json') as f:
            context.add_cookies(json.load(f))
        print("クッキー読み込み成功")
    except Exception as e:
        print(f"クッキー読み込み失敗: {e}")
    
    page = context.new_page()
    page.goto('https://salonboard.com/KLP/reserve/reserveList/searchDate?date=20251227')
    page.wait_for_timeout(3000)
    
    print(f"URL: {page.url}")
    print(f"タイトル: {page.title()}")
    
    tables = page.query_selector_all('table')
    print(f"テーブル数: {len(tables)}")
    
    found = False
    for i, table in enumerate(tables):
        header = table.query_selector('th#comingDate')
        if header:
            found = True
            print(f"予約テーブル発見: table[{i}]")
            rows = table.query_selector_all('tbody tr')
            print(f"行数: {len(rows)}")
            for j, row in enumerate(rows[:3]):
                link = row.query_selector('a[href*="reserveId="]')
                cells = row.query_selector_all('td')
                print(f"  row[{j}]: cells={len(cells)}, link={link is not None}")
                if not link:
                    # 他のリンクを探す
                    all_links = row.query_selector_all('a')
                    print(f"    全リンク数: {len(all_links)}")
                    for a in all_links[:2]:
                        href = a.get_attribute('href') or ''
                        print(f"    href: {href[:60]}")
    
    if not found:
        print("予約テーブル見つからず")
        if 'login' in page.url.lower():
            print("→ ログインが必要")
    
    browser.close()
    print("完了")
