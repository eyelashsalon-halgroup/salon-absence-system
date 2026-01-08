#!/usr/bin/env python3
"""予約キャンセル処理スクリプト"""
import os
import sys
import json
import requests
from datetime import datetime


# Xvfb仮想ディスプレイ起動（Railway用）
try:
    from pyvirtualdisplay import Display
    display = Display(visible=0, size=(1920, 1080))
    display.start()
    print("[OK] Xvfb仮想ディスプレイ起動", flush=True)
except Exception as e:
    print(f"[WARN] Xvfb起動スキップ: {e}", flush=True)
def login_to_salonboard(page):
    """SalonBoardにログイン"""
    login_id = os.environ.get('SALONBOARD_LOGIN_ID', 'CD18317')
    login_password = os.environ.get('SALONBOARD_LOGIN_PASSWORD', 'Ne8T2Hhi!')
    
    print('[LOGIN] ログイン処理開始', flush=True)
    page.goto('https://salonboard.com/login/', timeout=120000)
    page.wait_for_timeout(5000)
    
    try:
        # ID入力
        page.fill('input[name="userId"]', login_id)
        print('[LOGIN] ID入力成功', flush=True)
        page.wait_for_timeout(500)
        
        # パスワード入力
        page.fill('input[name="password"]', login_password)
        print('[LOGIN] パスワード入力成功', flush=True)
        page.wait_for_timeout(500)
        
        # Enterキーでログイン
        page.keyboard.press('Enter')
        print('[LOGIN] Enterキー押下', flush=True)
        
        # ページ遷移を待つ
        for i in range(30):
            page.wait_for_timeout(1000)
            current_url = page.url
            print(f'[LOGIN] {i+1}秒後URL: {current_url}', flush=True)
            if '/KLP/' in current_url or 'schedule' in current_url:
                print('[LOGIN] ログイン成功', flush=True)
                return True
            if 'login' not in current_url.lower():
                print('[LOGIN] ログイン成功（URLチェック）', flush=True)
                return True
        
        print('[LOGIN] タイムアウト', flush=True)
        return False
    except Exception as e:
        print(f'[LOGIN] エラー: {e}', flush=True)
        return False


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
                browser = p.chromium.launch(headless=False, args=['--disable-blink-features=AutomationControlled', '--no-sandbox', '--disable-dev-shm-usage'])
                context = browser.new_context()
                
                # Cookie読み込み
                cookie_file = os.path.join(os.path.dirname(__file__), 'session_cookies.json')
                try:
                    with open(cookie_file, 'r') as f:
                        cookies = json.load(f)
                    context.add_cookies(cookies)
                    print(f'[OK] クッキー読み込み: {len(cookies)}個', flush=True)
                except Exception as e:
                    print(f'[WARN] クッキー読み込み失敗: {e}', flush=True)
                
                page = context.new_page()
                visit_date = visit_datetime[:10].replace('/', '').replace('-', '')
                url = f'https://salonboard.com/KLP/schedule/salonSchedule/?date={visit_date}'
                print(f'[SalonBoard] アクセス: {url}', flush=True)
                
                try:
                    page.goto(url, timeout=120000)
                except Exception as e:
                    print(f'[SalonBoard] 初回アクセスエラー: {e}', flush=True)
                
                # ログインページにリダイレクトされたか確認
                if 'login' in page.url.lower() or 'エラー' in page.title():
                    print('[SalonBoard] セッション切れ、再ログイン実行', flush=True)
                    if login_to_salonboard(page):
                        # ログイン成功後、Cookie保存
                        new_cookies = context.cookies()
                        with open(cookie_file, 'w') as f:
                            json.dump(new_cookies, f)
                        print(f'[OK] 新しいCookie保存: {len(new_cookies)}個', flush=True)
                        
                        # 再度予約ページへ
                        page.goto(url, timeout=120000)
                    else:
                        print('[ERROR] ログイン失敗', flush=True)
                        browser.close()
                        raise Exception('ログイン失敗')
                
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
                    print('[OK] 予約セルをクリック', flush=True)
                    page.wait_for_timeout(3000)
                    
                    # 現在のURL確認
                    print(f'[DEBUG] クリック後URL: {page.url}', flush=True)
                    
                    # キャンセルボタンを探してクリック
                    # デバッグ: モーダル内の要素確認
                    modal_elements = page.query_selector_all("a, button")
                    print(f"[DEBUG] モーダル内要素数: {len(modal_elements)}", flush=True)
                    for el in modal_elements[:30]:
                        try:
                            txt = el.inner_text() or ""
                            cls = el.get_attribute("class") or ""
                            if "キャンセル" in txt or "cancel" in cls.lower():
                                print(f"[DEBUG] キャンセル関連: text={txt[:30]}, class={cls}", flush=True)
                            href = el.get_attribute("href") or ""
                            onclick = el.get_attribute("onclick") or ""
                            print(f"[DEBUG] href={href[:50]}, onclick={onclick[:50]}", flush=True)
                        except:
                            pass
                    cancel_btn = page.query_selector('.btnSizeCancelTable')
                    if cancel_btn:
                        print('[OK] キャンセルボタン発見', flush=True)
                        cancel_btn.evaluate("e => e.click()")
                        page.wait_for_timeout(5000)
                        
                        # 確認ダイアログのOKボタン
                        page.wait_for_timeout(5000)
                        print(f'[DEBUG] キャンセル後URL: {page.url}', flush=True)
                        
                        # ダイアログ内のボタンを探す
                        yes_btn = page.query_selector('button:has-text("はい"), button:has-text("OK"), input[value="はい"], input[value="OK"], a:has-text("はい"), a:has-text("OK"), .btn-primary, .okBtn')
                        
                        if not yes_btn:
                            # alertダイアログの場合
                            try:
                                page.on('dialog', lambda dialog: dialog.accept())
                                print('[DEBUG] ダイアログハンドラ設定', flush=True)
                            except:
                                pass
                            
                            # 全ボタンを確認
                            all_btns = page.query_selector_all('button, input[type="button"], input[type="submit"], a.btn')
                            print(f'[DEBUG] 全ボタン数: {len(all_btns)}', flush=True)
                            for btn in all_btns:
                                try:
                                    txt = btn.inner_text() or btn.get_attribute('value') or ''
                                    print(f'[DEBUG] ボタン: {txt}', flush=True)
                                except:
                                    pass
                        
                        if yes_btn:
                            print('[OK] 確認ボタン発見', flush=True)
                            yes_btn.click()
                            page.wait_for_timeout(5000)
                            cancel_success = True
                            print(f'[SalonBoardキャンセル成功] {booking_id}', flush=True)
                        else:
                            print('[ERROR] 確認ボタンが見つかりません', flush=True)
                    else:
                        print('[ERROR] キャンセルボタンが見つかりません', flush=True)
                        # ページ内容をデバッグ
                        try:
                            html = page.content()[:2000]
                            print(f'[DEBUG] ページ内容: {html}', flush=True)
                        except:
                            pass
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