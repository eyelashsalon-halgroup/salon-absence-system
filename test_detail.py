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
    
    # 神原良祐の詳細ページ
    booking_id = 'YF73556206'
    url = f'https://salonboard.com/KLP/reserve/ext/extReserveDetail/?reserveId={booking_id}'
    print(f"アクセス中: {url}")
    page.goto(url, timeout=30000)
    page.wait_for_timeout(3000)
    
    print(f"Title: {page.title()}")
    
    # 電話番号を取得
    page_text = page.inner_text('body')
    phone_match = re.search(r'0[0-9]{9,10}', page_text.replace('-', ''))
    if phone_match:
        print(f"電話番号: {phone_match.group()}")
    
    # メニューを取得
    menu_patterns = [
        r'【まつげエクステ】[^【\n]+',
        r'【その他まつげメニュー】[^【\n]+',
        r'【付替オフ】[^【\n]+',
        r'【次回】[^【\n]+'
    ]
    for pattern in menu_patterns:
        matches = re.findall(pattern, page_text)
        for match in matches:
            print(f"メニュー: {match[:50]}...")
    
    browser.close()
