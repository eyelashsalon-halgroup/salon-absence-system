#!/usr/bin/env python3
"""電話番号が空のBE予約のみを対象に電話番号を補完する軽量版"""

import os
import json
import re
import requests
from datetime import datetime
from playwright.sync_api import sync_playwright

SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_KEY')

def get_phone_from_customer_detail(page, booking_id):
    """予約詳細→お客様情報詳細から電話番号を取得"""
    try:
        url = f'https://salonboard.com/KLP/reserve/ext/extReserveDetail/?reserveId={booking_id}'
        page.goto(url, timeout=30000)
        page.wait_for_timeout(500)
        
        # まず予約詳細ページで電話番号を探す
        rows = page.query_selector_all('tr, .row, div')
        for row in rows:
            text = row.inner_text()
            if '電話番号' in text:
                phone_match = re.search(r'0[0-9]{9,10}', text.replace('-', ''))
                if phone_match:
                    print(f"[PHONE] {booking_id} 予約詳細から: {phone_match.group()}")
                    return phone_match.group()
        
        # なければ「お客様情報詳細」リンクをクリック
        customer_link = page.query_selector('a:has-text("お客様情報詳細")')
        if not customer_link:
            customer_link = page.query_selector('a[href*="customerDetail"]')
        
        if customer_link:
            customer_link.click()
            page.wait_for_timeout(1000)
            
            rows = page.query_selector_all('tr, .row, div')
            for row in rows:
                text = row.inner_text()
                if '電話番号' in text or '携帯' in text:
                    phone_match = re.search(r'0[0-9]{9,10}', text.replace('-', ''))
                    if phone_match:
                        print(f"[PHONE] {booking_id} 顧客詳細から: {phone_match.group()}")
                        return phone_match.group()
        
        print(f"[PHONE] {booking_id} 電話番号なし")
        return None
    except Exception as e:
        print(f"[PHONE] {booking_id} エラー: {e}")
        return None


def main():
    print(f"[PHONE-FILL] 開始: {datetime.now()}")
    
    headers = {
        'apikey': SUPABASE_KEY,
        'Authorization': f'Bearer {SUPABASE_KEY}',
        'Content-Type': 'application/json'
    }
    
    # 電話番号が空の予約を取得
    res = requests.get(
        f'{SUPABASE_URL}/rest/v1/8weeks_bookings?phone=eq.&select=booking_id,customer_name',
        headers=headers
    )
    empty_phone_bookings = res.json() if res.status_code == 200 else []
    print(f"[PHONE-FILL] 対象: {len(empty_phone_bookings)}件")
    
    if not empty_phone_bookings:
        print("[PHONE-FILL] 完了（対象なし）")
        return
    
    updated_count = 0
    
    try:
        cookie_file = os.path.join(os.path.dirname(__file__), 'session_cookies.json')
        with open(cookie_file, 'r') as f:
            cookies = json.load(f)
        
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context()
            context.add_cookies(cookies)
            page = context.new_page()
            
            for booking in empty_phone_bookings:
                booking_id = booking['booking_id']
                customer_name = booking['customer_name']
                
                phone = get_phone_from_customer_detail(page, booking_id)
                
                if phone:
                    update_res = requests.patch(
                        f'{SUPABASE_URL}/rest/v1/8weeks_bookings?booking_id=eq.{booking_id}',
                        headers=headers,
                        json={'phone': phone}
                    )
                    if update_res.status_code in [200, 204]:
                        print(f"[PHONE-FILL] 更新: {customer_name} → {phone}")
                        updated_count += 1
            
            browser.close()
    except Exception as e:
        print(f"[PHONE-FILL] エラー: {e}")
    
    print(f"[PHONE-FILL] 完了: {updated_count}件更新")


if __name__ == "__main__":
    main()
