from playwright.sync_api import sync_playwright
import json

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)
    context = browser.new_context()
    page = context.new_page()
    
    page.goto('https://salonboard.com/login/')
    page.wait_for_timeout(2000)
    
    print("SalonBoardにログインしてください...")
    print("ログイン完了後、Enterを押してください")
    input()
    
    cookies = context.cookies()
    with open('session_cookies.json', 'w') as f:
        json.dump(cookies, f)
    print(f"✅ Cookie保存完了: {len(cookies)}件")
    
    browser.close()
