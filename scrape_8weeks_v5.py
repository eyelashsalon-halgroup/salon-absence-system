#!/usr/bin/env python3
"""
8週間分の予約をスクレイピング【最適化版 v5】
- 詳細ページアクセスは電話番号がない予約のみ
- メニュー・経路は一覧ページから取得
"""
import json
import re
import os
import requests
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading

try:
    from pyvirtualdisplay import Display
    display = Display(visible=0, size=(1920, 1080))
    display.start()
    print("[OK] Xvfb仮想ディスプレイ起動", flush=True)
except Exception as e:
    print(f"[WARN] Xvfb起動スキップ: {e}", flush=True)

print("[STARTUP] scrape_8weeks_v5.py 開始", flush=True)

scrape_failure_count = 0
FAILURE_THRESHOLD = 5
JST = timezone(timedelta(hours=9))
SUPABASE_URL = os.environ.get('SUPABASE_URL', '')
SUPABASE_KEY = os.environ.get('SUPABASE_KEY', '')
db_lock = threading.Lock()
result_lock = threading.Lock()

def get_phone_for_customer(customer_name, booking_id):
    if not SUPABASE_KEY:
        return ''
    normalized_name = customer_name.replace(' ', '').replace('　', '')
    headers = {'apikey': SUPABASE_KEY, 'Authorization': f'Bearer {SUPABASE_KEY}'}
    res = requests.get(f'{SUPABASE_URL}/rest/v1/customers?name=ilike.*{normalized_name}*&select=phone', headers=headers)
    if res.status_code == 200 and res.json():
        phone = res.json()[0].get('phone', '')
        if phone:
            return phone
    return ''

def get_phone_from_salonboard(page, booking_id):
    result = {'phone': ''}
    try:
        if booking_id.startswith('BE'):
            url = f'https://salonboard.com/KLP/reserve/net/reserveDetail/?reserveId={booking_id}'
        else:
            url = f'https://salonboard.com/KLP/reserve/ext/extReserveDetail/?reserveId={booking_id}'
        page.goto(url, timeout=30000)
        page.wait_for_timeout(500)
        rows = page.query_selector_all('tr, .row, div')
        for row in rows:
            text = row.inner_text()
            if '電話番号' in text:
                phone_match = re.search(r'0[0-9]{9,10}', text.replace('-', ''))
                if phone_match:
                    result['phone'] = phone_match.group()
                    print(f"[DETAIL-SB] {booking_id} 電話: {result['phone']}", flush=True)
                    break
        if not result['phone'] and booking_id.startswith('BE'):
            try:
                customer_link = page.query_selector('a.btn_schedule_customer') or page.query_selector('a:has-text("お客様情報")')
                if customer_link:
                    customer_link.click()
                    page.wait_for_timeout(1000)
                    for row in page.query_selector_all('tr, .row, div'):
                        text = row.inner_text()
                        if '電話番号' in text or '携帯' in text:
                            phone_match = re.search(r'0[0-9]{9,10}', text.replace('-', ''))
                            if phone_match:
                                result['phone'] = phone_match.group()
                                break
            except:
                pass
    except Exception as e:
        print(f"[DETAIL-SB] エラー: {booking_id} - {e}")
    return result

def login_to_salonboard(page):
    login_id = os.environ.get('SALONBOARD_LOGIN_ID', 'CD18317')
    login_password = os.environ.get('SALONBOARD_LOGIN_PASSWORD', 'Ne8T2Hhi!')
    page.goto('https://salonboard.com/login/', timeout=60000)
    page.wait_for_timeout(1000)
    try:
        page.fill('input[name="userId"]', login_id)
        page.fill('input[name="password"]', login_password)
        btn = None
        for sel in ['a.common-CNCcommon__primaryBtn', 'button[type="submit"]', 'a:has-text("ログイン")']:
            try:
                btn = page.query_selector(sel)
                if btn:
                    break
            except:
                pass
        if btn:
            btn.click()
        else:
            page.keyboard.press('Enter')
        for i in range(30):
            page.wait_for_timeout(300)
            if '/KLP/' in page.url:
                print("[LOGIN] ログイン成功", flush=True)
                return True
        return False
    except Exception as e:
        print(f"[LOGIN] エラー: {e}", flush=True)
        return False

def reset_failure_count():
    global scrape_failure_count
    scrape_failure_count = 0
