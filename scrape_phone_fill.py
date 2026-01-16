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
    
    # 電話番号が空または不正（0005等）のBE予約を取得
    res = requests.get(
        f'{SUPABASE_URL}/rest/v1/8weeks_bookings?booking_id=like.BE*&select=booking_id,customer_name,phone',
        headers=headers
    )
    all_be = res.json() if res.status_code == 200 else []
    # 空または携帯番号パターン以外をフィルタ
    empty_phone = [b for b in all_be if not b.get('phone') or not re.match(r'^0[789]0', b.get('phone', ''))]
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
                    page.wait_for_timeout(2000)
                    
                    phone = None
                    
                    # ページ全体のテキストから携帯番号パターン(070/080/090)を検索
                    page_text = page.content()
                    # 携帯番号パターンのみ（070/080/090で始まる11桁）
                    matches = re.findall(r'0[789]0[\-]?\d{4}[\-]?\d{4}', page_text)
                    if matches:
                        # ハイフン除去して最初のマッチを使用
                        phone = matches[0].replace('-', '')
                        print(f"[PHONE-FILL] {booking_id} 電話発見: {phone}", flush=True)
                    else:
                        print(f"[PHONE-FILL] {booking_id} 携帯番号見つからず", flush=True)
                    
                    if phone and len(phone) == 11:
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
