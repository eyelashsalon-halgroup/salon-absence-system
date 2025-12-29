#!/usr/bin/env python3
"""SalonBoardメニュー管理画面の構造確認（手動ログイン対応）"""
import json
import os
from playwright.sync_api import sync_playwright

def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(
            user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
            viewport={'width': 1920, 'height': 1080}
        )
        
        page = context.new_page()
        
        # ログインページへ
        page.goto('https://salonboard.com/login/', timeout=60000)
        
        # 環境変数からID/パスワード取得
        login_id = os.getenv('SALONBOARD_LOGIN_ID', '')
        password = os.getenv('SALONBOARD_LOGIN_PASSWORD', '')
        
        if login_id and password:
            print("[INFO] 自動ログイン試行...")
            try:
                page.fill('input[name="loginId"]', login_id)
                page.fill('input[name="password"]', password)
                page.click('button[type="submit"], input[type="submit"]')
                page.wait_for_timeout(3000)
                print("[OK] ログイン送信完了")
            except Exception as e:
                print(f"[WARN] 自動ログイン失敗: {e}")
        else:
            print("[INFO] 環境変数なし。手動でログインしてください。")
        
        # ログイン完了まで待機
        print("[INFO] ログイン完了後、Enterを押してください...")
        input()
        
        # クッキー保存
        cookies = context.cookies()
        with open('session_cookies.json', 'w') as f:
            json.dump(cookies, f, indent=2, ensure_ascii=False)
        print("[OK] クッキー保存完了")
        
        # メニュー管理画面へ
        print("[INFO] メニュー管理画面へ移動...")
        page.goto('https://salonboard.com/CNK/draft/menuEdit', timeout=60000)
        page.wait_for_timeout(3000)
        
        print(f"\n=== 現在のURL ===\n{page.url}")
        print(f"\n=== 画面タイトル ===\n{page.title()}")
        
        # テーブル確認
        tables = page.query_selector_all('table')
        print(f"\n=== テーブル数: {len(tables)}個 ===")
        
        # 施術時間候補
        print("\n=== 「分」を含むテキスト ===")
        elements = page.query_selector_all('td, span, div, p')
        time_found = []
        for el in elements[:500]:
            text = el.text_content().strip()
            if '分' in text and len(text) < 30:
                if text not in time_found:
                    time_found.append(text)
        for t in time_found[:30]:
            print(f"  {t}")
        
        # HTML保存
        html = page.content()
        with open('menu_page.html', 'w', encoding='utf-8') as f:
            f.write(html)
        print("\n[OK] menu_page.html に保存")
        
        print("\n[INFO] ブラウザを確認してください。終了するにはEnterを押してください...")
        input()
        
        browser.close()

if __name__ == '__main__':
    main()
