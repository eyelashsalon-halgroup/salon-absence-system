from playwright.sync_api import sync_playwright
import json

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)
    context = browser.new_context()
    
    with open('session_cookies.json', 'r') as f:
        cookies = json.load(f)
        context.add_cookies(cookies)
    
    page = context.new_page()
    
    booking_id = 'YF73556206'
    url = f'https://salonboard.com/KLP/reserve/ext/extReserveDetail/?reserveId={booking_id}'
    page.goto(url, timeout=60000)
    page.wait_for_timeout(3000)
    
    route_text = page.inner_text('body')
    
    if '次回予約' in route_text:
        print("✅ 次回予約 検出")
    elif 'NHPB' in route_text or 'ホットペッパー' in route_text:
        print("✅ ホットペッパー 検出")
    else:
        print("❌ 予約経路 検出できず")
        if '予約経路' in route_text:
            idx = route_text.find('予約経路')
            print(f"予約経路周辺: {route_text[idx:idx+50]}")
    
    browser.close()
