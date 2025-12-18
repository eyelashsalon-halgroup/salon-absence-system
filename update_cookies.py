from playwright.sync_api import sync_playwright
import json

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)
    context = browser.new_context()
    page = context.new_page()
    
    page.goto('https://salonboard.com/login/')
    print("ブラウザでログインしてください。完了したらEnterを押してください。")
    input()
    
    cookies = context.cookies()
    with open('session_cookies.json', 'w') as f:
        json.dump(cookies, f, indent=2, ensure_ascii=False)
    print(f"クッキー保存完了: {len(cookies)}個")
    browser.close()
