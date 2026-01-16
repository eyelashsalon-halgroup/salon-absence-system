#!/usr/bin/env python3
"""電話番号が空のBE予約をSalonBoardから補完する軽量版"""
import os
import json
import re
import requests
from datetime import datetime

# 仮想ディスプレイ（Railway用）
try:
    from pyvirtualdisplay import Display
    display = Display(visible=0, size=(1920, 1080))
    display.start()
    print("[PHONE-FILL] Xvfb仮想ディスプレイ起動", flush=True)
except Exception as e:
    print(f"[PHONE-FILL] Xvfb起動スキップ: {e}", flush=True)

from playwright.sync_api import sync_playwright

SUPABASE_URL = os.environ.get('SUPABASE_URL')
SUPABASE_KEY = os.environ.get('SUPABASE_KEY')

def main():
    print(f"[PHONE-FILL] 開始: {datetime.now()}", flush=True)
    
    headers = {
        'apikey': SUPABASE_KEY,
        'Authorization': f'Bearer {SUPABASE_KEY}',
        'Content-Type': 'application/json'
    }
    
    # 電話番号が空のBE予約を取得
    res = requests.get(
        f'{SUPABASE_URL}/rest/v1/8weeks_bookings?booking_id=like.BE*&phone=eq.&select=booking_id,customer_name',
        headers=headers
    )
    empty_phone = res.json() if res.status_code == 200 else []
    print(f"[PHONE-FILL] 対象: {len(empty_phone)}件", flush=True)
    
    if not empty_phone:
        print("[PHONE-FILL] 完了（対象なし）", flush=True)
        return
    
    updated = 0
    
    try:
        cookie_file = os.path.join(os.path.dirname(__file__), 'session_cookies.json')
        with open(cookie_file, 'r') as f:
            cookies = json.load(f)
        
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=False,
                args=['--disable-blink-features=AutomationControlled', '--no-sandbox', '--disable-dev-shm-usage']
            )
            
            context = browser.new_context(
                user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
                viewport={'width': 1920, 'height': 1080},
                locale='ja-JP',
                timezone_id='Asia/Tokyo'
            )
            
            context.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
            """)
            
            context.add_cookies(cookies)
            page = context.new_page()
            
            for booking in empty_phone:
                booking_id = booking['booking_id']
                name = booking['customer_name']
                
                try:
                    url = f'https://salonboard.com/KLP/reserve/net/reserveDetail/?reserveId={booking_id}'
                    page.goto(url, timeout=30000)
                    page.wait_for_timeout(1000)
                    
                    phone = None
                    
                    # 1. ページ内で電話番号を直接検索
                    rows = page.query_selector_all('tr, .row, div, td, span')
                    for row in rows:
                        try:
                            text = row.inner_text()
                            if '電話' in text:
                                match = re.search(r'0[0-9]{9,10}', text.replace('-', ''))
                                if match:
                                    phone = match.group()
                                    print(f"[PHONE-FILL] {booking_id} 電話発見: {phone}", flush=True)
                                    break
                        except:
                            pass
                    
                    # 2. お客様情報リンクを探してクリック
                    if not phone:
                        customer_link = page.query_selector('a[href*="customer"], a:has-text("お客様"), a:has-text("顧客")')
                        if customer_link:
                            print(f"[PHONE-FILL] {booking_id} お客様情報リンク発見", flush=True)
                            customer_link.click()
                            page.wait_for_timeout(1500)
                            cust_rows = page.query_selector_all('tr, .row, div, td, span')
                            for row in cust_rows:
                                try:
                                    text = row.inner_text()
                                    if '電話' in text or '携帯' in text:
                                        match = re.search(r'0[0-9]{9,10}', text.replace('-', ''))
                                        if match:
                                            phone = match.group()
                                            print(f"[PHONE-FILL] {booking_id} 顧客詳細から電話発見: {phone}", flush=True)
                                            break
                                except:
                                    pass
                        else:
                            print(f"[PHONE-FILL] {booking_id} お客様情報リンクなし", flush=True)
                    
                    if phone:
                        update_res = requests.patch(
                            f'{SUPABASE_URL}/rest/v1/8weeks_bookings?booking_id=eq.{booking_id}',
                            headers=headers,
                            json={'phone': phone}
                        )
                        if update_res.status_code in [200, 204]:
                            print(f"[PHONE-FILL] 更新: {name} → {phone}", flush=True)
                            updated += 1
                    else:
                        print(f"[PHONE-FILL] 取得失敗: {name} ({booking_id})", flush=True)
                        
                except Exception as e:
                    print(f"[PHONE-FILL] エラー: {booking_id} - {e}", flush=True)
            
            browser.close()
    except Exception as e:
        print(f"[PHONE-FILL] 全体エラー: {e}", flush=True)
    
    print(f"[PHONE-FILL] 完了: {updated}件更新", flush=True)

if __name__ == "__main__":
    main()
