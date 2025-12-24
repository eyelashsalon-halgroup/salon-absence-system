#!/usr/bin/env python3
import json
import re
import os
from playwright.sync_api import sync_playwright
from datetime import datetime, timedelta, timezone

def login_to_salonboard(page):
    """サロンボードにID/パスワードでログイン"""
    login_id = os.environ.get('SALONBOARD_LOGIN_ID', 'CD18317')
    login_password = os.environ.get('SALONBOARD_LOGIN_PASSWORD', 'Ne8T2Hhi!')
    
    print("[LOGIN] ログインページにアクセス...")
    page.goto('https://salonboard.com/login/', timeout=60000)
    page.wait_for_timeout(3000)
    
    print("[LOGIN] ID入力...")
    page.fill('input[name="userId"]', login_id)
    page.wait_for_timeout(500)
    
    print("[LOGIN] パスワード入力...")
    page.fill('input[name="password"]', login_password)
    page.wait_for_timeout(500)
    
    print("[LOGIN] ログインボタンクリック...")
    try:
        btn = page.query_selector('a.common-CNCcommon__primaryBtn')
        if btn:
            btn.click()
        else:
            page.click('a:has-text("ログイン")')
    except:
        page.click('a:has-text("ログイン")')
    page.wait_for_timeout(5000)
    
    if 'login' in page.url.lower():
        print("[LOGIN] ログイン失敗")
        return False
    
    print(f"[LOGIN] ログイン成功: {page.url}")
    return True

with sync_playwright() as p:
    browser = p.chromium.launch(
        headless=True,
        args=['--disable-blink-features=AutomationControlled']
    )
    
    context = browser.new_context(
        user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        viewport={'width': 1920, 'height': 1080},
        locale='ja-JP',
        timezone_id='Asia/Tokyo'
    )
    
    # クッキーを読み込んで適用
    try:
        with open('session_cookies.json', 'r') as f:
            cookies = json.load(f)
        context.add_cookies(cookies)
        print("[COOKIE] クッキー読み込み成功")
    except:
        print("[COOKIE] クッキーファイルなし")
        cookies = []
    
    page = context.new_page()
    
    JST = timezone(timedelta(hours=9))
    today = (datetime.now(JST) + timedelta(days=3)).strftime('%Y%m%d')
    url = f'https://salonboard.com/KLP/reserve/reserveList/searchDate?date={today}'
    
    print(f"[SCRAPE] 本日の予約にアクセス（{today}）...")
    page.goto(url, timeout=90000)
    page.wait_for_timeout(3000)
    
    # デバッグ: 現在のURL確認
    print(f"[DEBUG] 現在のURL: {page.url}")
    print(f"[DEBUG] ページタイトル: {page.title()}")
    print(f"[DEBUG] テーブル数: {len(page.query_selector_all('table'))}")

    # ログイン状態確認 - ログインページまたはエラーページなら再ログイン
    if 'login' in page.url.lower() or 'エラー' in page.title() or len(page.query_selector_all('table')) == 0:
        print(f"[COOKIE] セッション無効検出 - 再ログイン実行")
        if not login_to_salonboard(page):
            print("[ERROR] ログイン失敗")
            browser.close()
            exit(1)
        
        # クッキーを更新して保存
        new_cookies = context.cookies()
        with open('session_cookies.json', 'w') as f:
            json.dump(new_cookies, f, indent=2, ensure_ascii=False)
        print(f"[COOKIE] 新しいクッキーを保存: {len(new_cookies)}個")
        
        # 再度予約ページにアクセス
        page.goto(url, timeout=90000)
        page.wait_for_timeout(3000)
    
    # 第1段階：予約IDと基本情報を取得
    basic_bookings = []
    seen_ids = set()
    rows = page.query_selector_all('table tbody tr')
    print(f"[SCRAPE] {len(rows)}行を検出")
    
    for row in rows:
        try:
            cells = row.query_selector_all('td')
            if len(cells) < 4:
                continue
            
            datetime_text = cells[0].text_content().strip()
            status = cells[1].text_content().strip()
            customer_name = cells[2].text_content().strip()
            
            if datetime_text.isdigit() or 'キャンセル' in status:
                continue
            if not datetime_text or not customer_name:
                continue
            
            id_match = re.search(r'\(([A-Z]{2}\d+)\)', customer_name)
            booking_id = id_match.group(1) if id_match else None
            
            if not booking_id or booking_id in seen_ids:
                continue
            seen_ids.add(booking_id)
            
            staff = cells[3].text_content().strip() if len(cells) > 3 else ""
            source = cells[4].text_content().strip() if len(cells) > 4 else ""
            menu = cells[5].text_content().strip() if len(cells) > 5 else ""
            
            basic_bookings.append({
                "来店日時": datetime_text,
                "ステータス": status,
                "お客様名": customer_name,
                "スタッフ": staff,
                "予約経路": source,
                "メニュー": menu,
                "予約ID": booking_id
            })
        except Exception as e:
            continue
    
    print(f"[SCRAPE] {len(basic_bookings)}件の予約IDを取得")
    
    # 第2段階：各予約の詳細から電話番号とお客様番号を取得
    bookings = []
    for i, booking in enumerate(basic_bookings):
        try:
            booking_id = booking["予約ID"]
            source = booking["予約経路"]
            print(f"[SCRAPE] ({i+1}/{len(basic_bookings)}) {booking['お客様名'][:20]}の詳細取得中...")
            
            if source == "NHPB":
                detail_url = f'https://salonboard.com/KLP/reserve/net/reserveDetail/?reserveid={booking_id}'
            else:
                detail_url = f'https://salonboard.com/KLP/reserve/ext/extReserveDetail/?reserveid={booking_id}'
            
            page.goto(detail_url)
            page.wait_for_timeout(2000)
            
            phone_cell = page.query_selector('tr:has-text("電話番号") td:nth-child(2)')
            phone = phone_cell.text_content().strip() if phone_cell else ""
            
            phone_match = re.search(r'(0\d{9,10})', phone)
            phone = phone_match.group(1) if phone_match else phone
            
            customer_number_cell = page.query_selector('tr:has-text("お客様番号") td:nth-child(2)')
            customer_number = customer_number_cell.text_content().strip() if customer_number_cell else ""
            
            booking["電話番号"] = phone
            booking["お客様番号"] = customer_number
            bookings.append(booking)
            print(f"[SCRAPE] 取得完了: {phone} / 番号:{customer_number} ({source})")
            
        except Exception as e:
            print(f"[ERROR] {booking_id}: {e}")
            booking["電話番号"] = ""
            booking["お客様番号"] = ""
            bookings.append(booking)
    
    browser.close()
    
    result = {
        "success": True,
        "bookings": bookings,
        "count": len(bookings),
        "date": today,
        "timestamp": datetime.now().isoformat()
    }
    
    result_file = f"scrape_result_3days.json"
    with open(result_file, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    
    print(f"\n[SCRAPE] 完了: {len(bookings)}件の予約を取得（電話番号+お客様番号付き）")
    print(f"[SCRAPE] 結果ファイル: {result_file}")