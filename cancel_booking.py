#!/usr/bin/env python3
"""予約キャンセル処理スクリプト"""
import os
import sys
import json
import requests
from datetime import datetime

def cancel_booking(booking_id, line_user_id):
    """SalonBoardで予約をキャンセル"""
    from playwright.sync_api import sync_playwright
    
    SUPABASE_URL = os.environ.get('SUPABASE_URL')
    SUPABASE_KEY = os.environ.get('SUPABASE_KEY')
    LINE_BOT_TOKEN = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN')
    
    print(f'[キャンセル処理開始] booking_id={booking_id}, line_user_id={line_user_id}', flush=True)
    
    try:
        # 予約情報を取得
        headers = {'apikey': SUPABASE_KEY, 'Authorization': f'Bearer {SUPABASE_KEY}'}
        res = requests.get(f'{SUPABASE_URL}/rest/v1/8weeks_bookings?booking_id=eq.{booking_id}', headers=headers)
        bookings = res.json()
        if not bookings:
            print(f'[キャンセルエラー] 予約が見つかりません: {booking_id}', flush=True)
            return
        
        booking = bookings[0]
        customer_name = booking.get('customer_name', '')
        visit_datetime = booking.get('visit_datetime', '')
        menu = booking.get('menu', '')
        staff = booking.get('staff', '指名なし')
        
        # SalonBoardでキャンセル実行
        cancel_success = False
        print(f'[SalonBoardキャンセル開始] booking_id={booking_id}, visit_datetime={visit_datetime}', flush=True)
        
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                context = browser.new_context()
                
                # Cookie読み込み
                try:
                    with open('session_cookies.json', 'r') as f:
                        cookies = json.load(f)
                    context.add_cookies(cookies)
                    print(f'[OK] クッキー読み込み: {len(cookies)}個', flush=True)
                except Exception as e:
                    print(f'[WARN] クッキー読み込み失敗: {e}', flush=True)
                
                page = context.new_page()
                visit_date = visit_datetime[:10].replace('/', '').replace('-', '')
                url = f'https://salonboard.com/KLP/schedule/salonSchedule/?date={visit_date}'
                print(f'[SalonBoard] アクセス: {url}', flush=True)
                page.goto(url, timeout=60000)
                
                # 予約要素が表示されるまで待つ
                try:
                    page.wait_for_selector('.scheduleReservation', timeout=30000)
                    print('[OK] 予約要素を検出', flush=True)
                except:
                    print('[ERROR] 予約要素が見つかりません', flush=True)
                
                # 予約セルを検索
                normalized_name = customer_name.replace('　', ' ').strip()
                print(f'[SalonBoardキャンセル] 検索: 顧客名={normalized_name}', flush=True)
                
                all_reservations = page.query_selector_all('div.scheduleReservation')
                print(f'[SalonBoardキャンセル] 予約セル数: {len(all_reservations)}', flush=True)
                
                reserve_element = None
                for el in all_reservations:
                    title_el = el.query_selector('li.scheduleReserveName')
                    if title_el:
                        title_text = title_el.get_attribute('title') or ''
                        title_name = title_text.replace('★', '').replace('様', '').replace('　', ' ').strip()
                        if normalized_name == title_name:
                            reserve_element = el
                            print(f'[OK] 予約セル発見: {title_text}', flush=True)
                            break
                
                if reserve_element:
                    reserve_element.click()
                    page.wait_for_timeout(2000)
                    
                    # キャンセルボタンを探してクリック
                    cancel_btn = page.query_selector('button:has-text("キャンセル"), a:has-text("キャンセル"), input[value="キャンセル"]')
                    if cancel_btn:
                        cancel_btn.click()
                        page.wait_for_timeout(2000)
                        
                        # 確認ダイアログのOKボタン
                        yes_btn = page.query_selector('button:has-text("はい"), button:has-text("OK"), input[value="はい"]')
                        if yes_btn:
                            yes_btn.click()
                            page.wait_for_timeout(2000)
                            cancel_success = True
                            print(f'[SalonBoardキャンセル成功] {booking_id}', flush=True)
                else:
                    print(f'[ERROR] 予約要素が見つかりません: {booking_id}', flush=True)
                
                browser.close()
        except Exception as e:
            print(f'[SalonBoardキャンセルエラー] {e}', flush=True)
        
        # 8weeks_bookingsから削除
        if cancel_success:
            requests.delete(f'{SUPABASE_URL}/rest/v1/8weeks_bookings?booking_id=eq.{booking_id}', headers=headers)
        
        # 通知送信
        def send_line_message(user_id, message):
            url = 'https://api.line.me/v2/bot/message/push'
            headers = {
                'Content-Type': 'application/json',
                'Authorization': f'Bearer {LINE_BOT_TOKEN}'
            }
            data = {'to': user_id, 'messages': [{'type': 'text', 'text': message}]}
            requests.post(url, headers=headers, json=data)
        
        status_text = "キャンセル完了" if cancel_success else "キャンセル依頼（手動対応必要）"
        message = f'[{status_text}]\nお客様：{customer_name}\n日時：{visit_datetime}\nメニュー：{menu}\nスタッフ：{staff}'
        
        # スタッフに通知
        for staff_id in ['U9022782f05526cf7632902acaed0cb08', 'U1d1dfe1993f1857327678e37b607187a']:
            try:
                send_line_message(staff_id, message)
                print(f'[キャンセル通知送信] {staff_id}', flush=True)
            except Exception as e:
                print(f'[キャンセル通知エラー] {staff_id}: {e}', flush=True)
        
        # 顧客にも通知（成功時のみ）
        if line_user_id and cancel_success:
            try:
                customer_msg = f'予約をキャンセルしました。\n\n日時：{visit_datetime}\nメニュー：{menu}\n\nまたのご予約お待ちしております。'
                send_line_message(line_user_id, customer_msg)
            except Exception as e:
                print(f'[顧客通知エラー] {e}', flush=True)
        
        print(f'[キャンセル処理完了] {customer_name} {visit_datetime} success={cancel_success}', flush=True)
        
    except Exception as e:
        print(f'[キャンセル処理エラー] {e}', flush=True)
        import traceback
        traceback.print_exc()

if __name__ == '__main__':
    if len(sys.argv) >= 3:
        booking_id = sys.argv[1]
        line_user_id = sys.argv[2]
        cancel_booking(booking_id, line_user_id)
    else:
        print('Usage: python3 cancel_booking.py <booking_id> <line_user_id>', flush=True)
