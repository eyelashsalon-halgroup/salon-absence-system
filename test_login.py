from playwright.sync_api import sync_playwright
import os

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)
    page = browser.new_page()
    
    # ログインページへ
    page.goto('https://salonboard.com/login/')
    page.wait_for_timeout(3000)
    print(f"1. ログインページ: {page.url}")
    
    # 入力
    page.fill('input[name="userId"]', os.environ.get('SALONBOARD_LOGIN_ID', 'CD18317'))
    page.fill('input[name="password"]', os.environ.get('SALONBOARD_LOGIN_PASSWORD', 'Ne8T2Hhi!'))
    print("2. ID/PW入力完了")
    
    # Enter
    page.keyboard.press('Enter')
    print("3. Enter押下")
    
    # 待機
    for i in range(10):
        page.wait_for_timeout(1000)
        print(f"4. {i+1}秒後: {page.url}")
        if '/KLP/' in page.url:
            print("ログイン成功!")
            break
    
    print(f"5. 最終URL: {page.url}")
    print(f"6. タイトル: {page.title()}")
    
    input("確認後Enterで終了...")
    browser.close()
