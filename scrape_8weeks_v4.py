#!/usr/bin/env python3
"""
8週間分の予約をスクレイピングして8weeks_bookingsテーブルに保存
詳細ページをスキップ、一覧ページから直接保存
"""
import json
import re
import os
import requests
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading
# 仮想ディスプレイ（Railway用）
try:
    from pyvirtualdisplay import Display
    display = Display(visible=0, size=(1920, 1080))
    display.start()
    print("[OK] Xvfb仮想ディスプレイ起動", flush=True)
except Exception as e:
    print(f"[WARN] Xvfb起動スキップ: {e}", flush=True)

print(f"[STARTUP] scrape_8weeks_v3.py 開始", flush=True)

# アラート用グローバル変数
scrape_failure_count = 0
FAILURE_THRESHOLD = 5

JST = timezone(timedelta(hours=9))

SUPABASE_URL = os.environ.get('SUPABASE_URL', 'https://lsrbeugmqqqklywmvjjs.supabase.co')
SUPABASE_KEY = os.environ.get('SUPABASE_KEY', '')

def get_phone_for_customer(customer_name, booking_id):
    """顧客の電話番号を取得（customersテーブルから検索）"""
    if not SUPABASE_KEY:
        return ''
    # スペース除去（半角・全角両方）
    normalized_name = customer_name.replace(' ', '').replace('　', '')
    headers = {'apikey': SUPABASE_KEY, 'Authorization': f'Bearer {SUPABASE_KEY}'}
    res = requests.get(
        f'{SUPABASE_URL}/rest/v1/customers?name=ilike.*{normalized_name}*&select=phone',
        headers=headers
    )
    if res.status_code == 200 and res.json():
        phone = res.json()[0].get('phone', '')
        if phone:
            print(f"[PHONE] {customer_name} → {phone}")
            return phone
    return ''

def get_details_from_salonboard(page, booking_id):
    """SalonBoardの予約詳細から電話番号、メニュー、予約経路を取得"""
    result = {'phone': '', 'menu': '', 'booking_source': None}
    try:
        # 予約詳細ページにアクセス
        url = f'https://salonboard.com/KLP/reserve/ext/extReserveDetail/?reserveId={booking_id}'
        page.goto(url, timeout=30000)
        page.wait_for_timeout(500)
        
        page_content = page.content()
        import re
        
        # 電話番号を取得
        rows = page.query_selector_all('tr, .row, div')
        for row in rows:
            text = row.inner_text()
            if '電話番号' in text:
                phone_match = re.search(r'0[0-9]{9,10}', text.replace('-', ''))
                if phone_match:
                    result['phone'] = phone_match.group()
                    print(f"[DETAIL-SB] {booking_id} 電話: {result['phone']}")
                    break
        
        # メニューを取得（ページのテキストから抽出）
        import re
        try:
            page_text = page.inner_text('body')
            menu_patterns = [
                r'【まつげエクステ】[^【\n]+',
                r'【その他まつげメニュー】[^【\n]+',
                r'【付替オフ】[^【\n]+',
                r'【次回】[^【\n]+'
            ]
            menu_parts = []
            for pattern in menu_patterns:
                matches = re.findall(pattern, page_text)
                for match in matches:
                    clean = match.strip()
                    if clean and len(clean) > 5 and clean not in menu_parts:
                        menu_parts.append(clean)
            if menu_parts:
                result['menu'] = ' / '.join(menu_parts[:3])[:300]
                print(f"[DETAIL-SB] {booking_id} メニュー: {result['menu'][:50]}...")
        except Exception as e:
            print(f"[DETAIL-SB] メニュー取得エラー: {e}")
        
        # 予約経路を取得（テキストから検索）
        try:
            route_text = page.inner_text('body')
            if '次回予約' in route_text:
                result['booking_source'] = '次回'
                print(f"[DETAIL-SB] {booking_id} 経路: 次回予約")
            elif 'NHPB' in route_text or 'ホットペッパー' in route_text:
                result['booking_source'] = 'NHPB'
                print(f"[DETAIL-SB] {booking_id} 経路: ホットペッパー")
            else:
                print(f"[DETAIL-SB] {booking_id} 経路: 不明")
        except Exception as e:
            print(f"[DETAIL-SB] {booking_id} 経路取得エラー: {e}")
        
    except Exception as e:
        print(f"[DETAIL-SB] エラー: {booking_id} - {e}")
    return result

def get_phone_from_salonboard(page, booking_id):
    """後方互換性のため残す"""
    result = get_details_from_salonboard(page, booking_id)
    return result['phone']


# スレッドセーフなロック
db_lock = threading.Lock()
result_lock = threading.Lock()

def scrape_date_range(worker_id, start_day, end_day, existing_cache, headers, today):
    """指定範囲の日付をスクレイピング（1ワーカー）"""
    import re
    from playwright.sync_api import sync_playwright
    
    print(f"[W{worker_id}] 開始: {start_day}〜{end_day-1}日目", flush=True)
    
    bookings_list = []
    slots_list = []
    
    try:
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
            
            try:
                with open('session_cookies.json', 'r') as f:
                    cookies = json.load(f)
                context.add_cookies(cookies)
            except:
                pass
            
            page = context.new_page()
            
            for day_offset in range(start_day, end_day):
                target_date = today + timedelta(days=day_offset)
                date_str = target_date.strftime('%Y%m%d')
                url = f'https://salonboard.com/KLP/reserve/reserveList/searchDate?date={date_str}'
                
                try:
                    page.goto(url, timeout=60000)
                    page.wait_for_timeout(150)
                except Exception as e:
                    print(f"[W{worker_id}] {target_date.strftime('%Y-%m-%d')} エラー: {e}", flush=True)
                    continue
                
                # 初回のみログイン確認
                if day_offset == start_day and ('login' in page.url.lower() or 'エラー' in page.title() or len(page.query_selector_all('table')) == 0):
                    if not login_to_salonboard(page):
                        print(f"[W{worker_id}] ログイン失敗", flush=True)
                        browser.close()
                        return [], []
                    
                    with db_lock:
                        new_cookies = context.cookies()
                        with open('session_cookies.json', 'w') as f:
                            json.dump(new_cookies, f, indent=2, ensure_ascii=False)
                    
                    page.goto(url, timeout=60000)
                    page.wait_for_timeout(150)
                
                # 予約テーブル取得
                reservation_table = None
                for table in page.query_selector_all("table"):
                    if table.query_selector("th#comingDate"):
                        reservation_table = table
                        break
                
                if not reservation_table:
                    continue
                
                rows = reservation_table.query_selector_all('tbody tr')
                
                for row in rows:
                    try:
                        cells = row.query_selector_all('td')
                        if len(cells) < 4:
                            continue
                        
                        # 受付待ちフィルター
                        status_text = cells[1].text_content().strip()
                        if "受付待ち" not in status_text:
                            continue
                        
                        # リンク取得（v3形式: cells[2]から）
                        reserve_link = cells[2].query_selector("a[href*='reserveId=']")
                        if not reserve_link:
                            continue
                        
                        href = reserve_link.get_attribute('href')
                        id_match = re.search(r'reserveId=([A-Z]{2}\d+)', href)
                        if not id_match:
                            continue
                        
                        booking_id = id_match.group(1)
                        
                        # 名前取得（v3形式）
                        name_elem = cells[2].query_selector("p.wordBreak")
                        customer_name = name_elem.text_content().strip() if name_elem else ""
                        customer_name = re.sub(r'[★☆♪♡⭐️🦁]', '', customer_name).strip()

                        
                        # 時間取得（v3形式）
                        time_cell = cells[0].text_content().strip()
                        time_match = re.search(r'(\d{1,2}:\d{2})', time_cell)
                        time_only = time_match.group(1) if time_match else "00:00"
                        visit_datetime = f"{target_date.strftime('%Y-%m-%d')} {time_only}:00"
                        
                        # スタッフ取得（v3形式）
                        staff_text = cells[3].text_content().strip() if len(cells) > 3 else ''
                        staff_name = re.sub(r'^\(指\)', '', staff_text).strip()

                        
                        cached = existing_cache.get(booking_id, {})
                        cached_menu = cached.get('menu', '')
                        cached_phone = cached.get('phone', '')
                        
                        # キャッシュのメニューが有効か確認
                        menu = ''
                        if cached_menu and '\n' not in cached_menu and '来店日' not in cached_menu and len(cached_menu) <= 200:
                            menu = cached_menu
                        
                        phone = cached_phone
                        if not phone:
                            phone = get_phone_for_customer(customer_name, booking_id)
                        
                        # Phase 1: 詳細取得はスキップ（後でまとめて取得）
                        cached_booking_source = existing_cache.get(booking_id, {}).get('booking_source')
                        booking_source = cached_booking_source
                        is_new_booking = booking_id not in existing_cache
                        needs_detail = not phone  # 電話番号がない場合のみ詳細取得
                        
                        bookings_list.append({
                            'booking_id': booking_id,
                            'customer_name': customer_name,
                            'visit_datetime': visit_datetime,
                            'staff': staff_name,
                            'menu': menu,
                            'phone': phone,
                            'status': '予約確定',
                            'booking_source': booking_source,
                            'needs_detail': needs_detail
                        })
                    except Exception as e:
                        print(f"[ERROR] 予約処理エラー: {booking_id if 'booking_id' in dir() else 'unknown'} - {e}", flush=True)
                        # リトライ1回
                        try:
                            page.wait_for_timeout(300)
                            page.goto(url, timeout=60000)
                            page.wait_for_timeout(150)
                        except:
                            pass
                        continue
                
                
                # === 詳細取得（日付の処理終了後、同じブラウザで）===
                needs_detail_list = [b for b in bookings_list if b.get('needs_detail', False)]
                for b in needs_detail_list:
                    try:
                        details = get_details_from_salonboard(page, b['booking_id'])
                        if details['phone']:
                            b['phone'] = details['phone']
                        if details['menu']:
                            b['menu'] = details['menu']
                        if details['booking_source']:
                            b['booking_source'] = details['booking_source']
                        b['needs_detail'] = False
                    except Exception as e:
                        print(f"[W{worker_id}] 詳細エラー {b['booking_id']}", flush=True)
                
                # === 空き枠取得（スケジュール画面から）===
                import math
                schedule_url = f'https://salonboard.com/KLP/schedule/salonSchedule/?date={date_str}'
                try:
                    page.goto(schedule_url, timeout=60000)
                    page.wait_for_selector('.scheduleMainTableLine', timeout=10000)
                    page.wait_for_timeout(150)
                    
                    staff_list = []
                    staff_options = page.query_selector_all('#stockNameList option')
                    for opt in staff_options:
                        value = opt.get_attribute('value') or ''
                        name = opt.inner_text()
                        if value.startswith('STAFF_'):
                            staff_list.append({'id': value.split('_')[1], 'name': name})
                    
                    staff_rows = page.query_selector_all('.jscScheduleMainTableStaff .scheduleMainTableLine')
                    
                    for idx, row in enumerate(staff_rows):
                        if idx >= len(staff_list):
                            break
                        staff_info = staff_list[idx]
                        
                        time_list = row.query_selector_all('.scheduleTime')
                        start_time = 9
                        if time_list:
                            first_time = time_list[0].inner_text()
                            try:
                                start_time = int(first_time.split(':')[0])
                            except:
                                pass
                        
                        booked_slots = []
                        reservations = row.query_selector_all('.scheduleReservation, .scheduleToDo')
                        for res in reservations:
                            time_zone = res.query_selector('.scheduleTimeZoneSetting')
                            if time_zone:
                                try:
                                    time_text = time_zone.inner_text()
                                    times = json.loads(time_text)
                                    if len(times) >= 2:
                                        start_parts = times[0].split(':')
                                        end_parts = times[1].split(':')
                                        start_h = int(start_parts[0]) + int(start_parts[1]) / 60
                                        end_h = int(end_parts[0]) + int(end_parts[1]) / 60
                                        booked_slots.append({'start': start_h, 'end': end_h})
                                except:
                                    pass
                        
                        day_off = row.query_selector('.isDayOff')
                        is_day_off = day_off is not None
                        
                        # .scheduleToDoが終日をカバーしているか、または予約が0件なら休日
                        if not is_day_off:
                            todos = row.query_selector_all('.scheduleToDo')
                            for todo in todos:
                                style = todo.get_attribute('style') or ''
                                # styleなし、またはwidth>=1000(ほぼ終日)なら休日
                                if not style or 'left' not in style or 'width' not in style:
                                    is_day_off = True
                                    break
                                # width値を抽出してチェック
                                import re
                                width_match = re.search(r'width:\s*(\d+)', style)
                                if width_match and int(width_match.group(1)) >= 1000:
                                    is_day_off = True
                                    break
                        
                        available_slots = []
                        if not is_day_off:
                            booked_slots.sort(key=lambda x: x['start'])
                            current = start_time
                            for slot in booked_slots:
                                if slot['start'] > current:
                                    start_min = current * 60
                                    end_min = slot['start'] * 60
                                    start_min_rounded = math.ceil(start_min / 10) * 10
                                    end_min_rounded = math.floor(end_min / 10) * 10
                                    if end_min_rounded > start_min_rounded:
                                        start_str = f"{int(start_min_rounded // 60)}:{int(start_min_rounded % 60):02d}"
                                        end_str = f"{int(end_min_rounded // 60)}:{int(end_min_rounded % 60):02d}"
                                        available_slots.append({'start': start_str, 'end': end_str})
                                current = max(current, slot['end'])
                            if current < 19:
                                current_min = current * 60
                                current_min_rounded = math.ceil(current_min / 10) * 10
                                start_str = f"{int(current_min_rounded // 60)}:{int(current_min_rounded % 60):02d}"
                                available_slots.append({'start': start_str, 'end': '19:00'})
                        
                        slots_list.append({
                            'date': date_str,
                            'staff_id': staff_info['id'],
                            'staff_name': staff_info['name'],
                            'is_day_off': is_day_off,
                            'slots': available_slots
                        })
                except Exception as e:
                    print(f"[W{worker_id}] 空き枠取得エラー {date_str}: {e}", flush=True)

                print(f"[W{worker_id}] {target_date.strftime('%m/%d')} 完了", flush=True)
            
            browser.close()
    except Exception as e:
        print(f"[W{worker_id}] 例外: {e}", flush=True)
    
    print(f"[W{worker_id}] 終了: {len(bookings_list)}件", flush=True)
    return bookings_list, slots_list



def login_to_salonboard(page):
    login_id = os.environ.get('SALONBOARD_LOGIN_ID', 'CD18317')
    login_password = os.environ.get('SALONBOARD_LOGIN_PASSWORD', 'Ne8T2Hhi!')
    
    print(f"[LOGIN] ログインページにアクセス中...", flush=True)
    page.goto('https://salonboard.com/login/', timeout=60000)
    page.wait_for_timeout(1000)
    
    try:
        page.fill('input[name="userId"]', login_id)
        page.fill('input[name="password"]', login_password)
        print(f"[LOGIN] ID/PW入力完了", flush=True)
        
        # ログインボタンをクリック
        btn = None
        selectors = [
            'a.common-CNCcommon__primaryBtn',
            'button[type="submit"]',
            'input[type="submit"]',
            'a.loginBtn',
            '.loginBtn',
            'button.primary',
            'a:has-text("ログイン")',
            'button:has-text("ログイン")'
        ]
        for sel in selectors:
            try:
                btn = page.query_selector(sel)
                if btn:
                    print(f"[LOGIN] ボタン発見: {sel}", flush=True)
                    break
            except:
                pass
        
        if btn:
            btn.click()
            print(f"[LOGIN] ボタンクリック", flush=True)
        else:
            print(f"[LOGIN] ボタン見つからず、Enter押下", flush=True)
            page.keyboard.press('Enter')
        
        # ページ遷移を待つ
        for i in range(30):
            page.wait_for_timeout(300)
            current_url = page.url
            if '/KLP/' in current_url:
                print(f"[LOGIN] ログイン成功", flush=True)
                return True
            # doLogin後の遷移を待つ
            if 'doLogin' in current_url:
                print(f"[LOGIN] doLogin処理中...", flush=True)
                continue
        
        print(f"[LOGIN] タイムアウト: {page.url}", flush=True)
        return False
    except Exception as e:
        print(f"[LOGIN] エラー: {e}", flush=True)
        return False

def send_scrape_alert(failure_count, error_message=""):
    LINE_CHANNEL_ACCESS_TOKEN_STAFF = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN_STAFF')
    LINE_USER_ID_HAL = os.environ.get('LINE_USER_ID_HAL')
    if not LINE_CHANNEL_ACCESS_TOKEN_STAFF or not LINE_USER_ID_HAL:
        return False
    message = f"⚠️ スクレイピング連続失敗\n連続失敗: {failure_count}回\nエラー: {error_message[:100] if error_message else '不明'}"
    headers = {'Authorization': f'Bearer {LINE_CHANNEL_ACCESS_TOKEN_STAFF}', 'Content-Type': 'application/json'}
    data = {'to': LINE_USER_ID_HAL, 'messages': [{'type': 'text', 'text': message}]}
    try:
        requests.post('https://api.line.me/v2/bot/message/push', headers=headers, json=data, timeout=10)
        return True
    except:
        return False

def reset_failure_count():
    global scrape_failure_count
    scrape_failure_count = 0

def increment_failure_count(error_message=""):
    global scrape_failure_count
    scrape_failure_count += 1
    if scrape_failure_count == FAILURE_THRESHOLD:
        send_scrape_alert(scrape_failure_count, error_message)

def main(days_limit=56):
    mode = "高速版（14日）" if days_limit <= 14 else "通常版（8週間）"
    print(f"[{datetime.now(JST)}] 予約スクレイピング {mode} 開始", flush=True)
    
    try:
        from playwright.sync_api import sync_playwright
        print("[OK] playwright インポート成功", flush=True)
    except Exception as e:
        print(f"[ERROR] playwright インポート失敗: {e}", flush=True)
        return
    
    SUPABASE_URL = os.environ.get('SUPABASE_URL')
    SUPABASE_KEY = os.environ.get('SUPABASE_KEY')
    
    if not SUPABASE_URL or not SUPABASE_KEY:
        print("[ERROR] SUPABASE環境変数がありません", flush=True)
        return
    
    print(f"[OK] SUPABASE_URL: {SUPABASE_URL[:30]}...", flush=True)
    
    headers = {
        'apikey': SUPABASE_KEY,
        'Authorization': f'Bearer {SUPABASE_KEY}',
        'Content-Type': 'application/json',
        'Prefer': 'resolution=merge-duplicates'
    }
    
    # 既存データをキャッシュ
    existing_cache = {}
    try:
        cache_res = requests.get(
            f"{SUPABASE_URL}/rest/v1/8weeks_bookings?select=booking_id,menu,phone,booking_source",
            headers=headers
        )
        if cache_res.status_code == 200:
            for item in cache_res.json():
                existing_cache[item['booking_id']] = {'menu': item.get('menu', ''), 'phone': item.get('phone', ''), 'booking_source': item.get('booking_source')}
            print(f"[CACHE] 既存データ: {len(existing_cache)}件", flush=True)
    except Exception as e:
        print(f"[CACHE] キャッシュ取得エラー: {e}", flush=True)
    
    today = datetime.now(JST)
    all_bookings = []
    all_slots = []
    
    # days_limitに応じて分割
    if days_limit <= 14:
        ranges = [(0, 3), (3, 5), (5, 8), (8, 10), (10, 12), (12, days_limit)]
    else:
        ranges = [(0, 10), (10, 19), (19, 28), (28, 37), (37, 46), (46, days_limit)]
    
    print("[PARALLEL] 6ワーカーで並列実行開始", flush=True)
    start_time = datetime.now(JST)
    
    with ThreadPoolExecutor(max_workers=6) as executor:
        futures = {
            executor.submit(scrape_date_range, i+1, start, end, existing_cache, headers, today): i
            for i, (start, end) in enumerate(ranges)
        }
        
        for future in as_completed(futures):
            worker_id = futures[future]
            try:
                bookings, slots = future.result()
                with result_lock:
                    all_bookings.extend(bookings)
                    all_slots.extend(slots)
                print(f"[PARALLEL] Worker{worker_id+1} 完了: {len(bookings)}件", flush=True)
            except Exception as e:
                print(f"[PARALLEL] Worker{worker_id+1} 例外: {e}", flush=True)
    
    end_time = datetime.now(JST)
    elapsed = (end_time - start_time).total_seconds()
    print(f"[PARALLEL] 全ワーカー完了: 合計{len(all_bookings)}件 ({elapsed:.1f}秒)", flush=True)
    
    # 神原良祐の予約を確認
    kambara_bookings = [b for b in all_bookings if '神原' in b.get('customer_name', '')]
    if kambara_bookings:
        for kb in kambara_bookings:
            print(f"[神原予約] {kb['booking_id']} {kb['visit_datetime']}", flush=True)
    
    # SalonBoardにない予約をDBから削除（一時的に無効化）
    # TODO: 削除ロジックはスクレイピングの安定性が確認できてから再有効化
    # if all_bookings:
    #     scraped_booking_ids = set(b['booking_id'] for b in all_bookings)
    #     ...
    
    # Phase 2: 詳細が必要な予約だけ取得（高速版はスキップ）
    needs_detail_bookings = [b for b in all_bookings if b.get('needs_detail', False)]
    print(f"[PHASE2] 詳細取得が必要な予約: {len(needs_detail_bookings)}件", flush=True)
    
    if days_limit <= 14:
        print(f"[PHASE2] 高速版のためスキップ（通常版で取得）", flush=True)
        needs_detail_bookings = []
    
    if needs_detail_bookings:
        
        # 詳細取得用のブラウザを1つ起動
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                context = browser.new_context()
                page = context.new_page()
                
                # ログイン（共通関数を使用）
                if not login_to_salonboard(page):
                    print("[PHASE2] ログイン失敗、スキップ", flush=True)
                else:
                
                    # 詳細取得
                    for booking in needs_detail_bookings:
                        try:
                            details = get_details_from_salonboard(page, booking['booking_id'])
                            if details['phone']:
                                booking['phone'] = details['phone']
                            if details['menu']:
                                booking['menu'] = details['menu']
                            if details['booking_source']:
                                booking['booking_source'] = details['booking_source']
                            print(f"[PHASE2] 詳細取得完了: {booking['booking_id']}", flush=True)
                        except Exception as e:
                            print(f"[PHASE2] 詳細取得エラー: {booking['booking_id']} - {e}", flush=True)
                
                browser.close()
        except Exception as e:
            print(f"[PHASE2] ブラウザエラー: {e}", flush=True)
    
    # needs_detailフラグを削除
    for b in all_bookings:
        b.pop('needs_detail', None)
    
    # DBに一括保存（バッチ）
    total_saved = 0
    if all_bookings:
        try:
            upsert_headers = headers.copy()
            upsert_headers["Prefer"] = "resolution=merge-duplicates"
            # 50件ずつバッチ処理
            batch_size = 50
            for i in range(0, len(all_bookings), batch_size):
                batch = all_bookings[i:i+batch_size]
                res = requests.post(
                    f"{SUPABASE_URL}/rest/v1/8weeks_bookings?on_conflict=booking_id",
                    headers=upsert_headers,
                    json=batch
                )
                if res.status_code in [200, 201]:
                    total_saved += len(batch)
                else:
                    print(f"[DB] バッチエラー: {res.status_code} - {res.text[:100]}", flush=True)
            print(f"[DB] {total_saved}件一括保存完了", flush=True)
        except Exception as e:
            print(f"[DB] 保存エラー: {e}", flush=True)
    
    # 空き枠をDBに保存
    slots_saved = 0
    if all_slots:
        try:
            slot_headers = headers.copy()
            slot_headers["Prefer"] = "resolution=merge-duplicates"
            batch_size = 50
            for i in range(0, len(all_slots), batch_size):
                batch = all_slots[i:i+batch_size]
                # updated_atを追加
                for slot in batch:
                    slot['updated_at'] = datetime.now(JST).isoformat()
                res = requests.post(
                    f"{SUPABASE_URL}/rest/v1/available_slots?on_conflict=date,staff_id",
                    headers=slot_headers,
                    json=batch
                )
                if res.status_code in [200, 201]:
                    slots_saved += len(batch)
                else:
                    print(f"[SLOTS] バッチエラー: {res.status_code} - {res.text[:100]}", flush=True)
            print(f"[SLOTS] {slots_saved}件の空き枠保存完了", flush=True)
        except Exception as e:
            print(f"[SLOTS] 保存エラー: {e}", flush=True)
    
    # === サロンボードにない予約をDBから削除 ===
    if all_bookings:
        try:
            # スクレイピングで取得したbooking_idリスト
            scraped_ids = set(b['booking_id'] for b in all_bookings)
            
            # 対象日付範囲のDB予約を取得
            start_date = today.strftime('%Y-%m-%d')
            end_date = (today + timedelta(days=days_limit)).strftime('%Y-%m-%d')
            
            db_res = requests.get(
                f"{SUPABASE_URL}/rest/v1/8weeks_bookings?visit_datetime=gte.{start_date}&visit_datetime=lt.{end_date}&select=booking_id",
                headers=headers
            )
            
            if db_res.status_code == 200:
                db_bookings = db_res.json()
                db_ids = set(b['booking_id'] for b in db_bookings)
                
                # DBにあるがスクレイピング結果にない = 削除された予約
                to_delete = db_ids - scraped_ids
                
                if to_delete:
                    delete_headers = headers.copy()
                    for bid in to_delete:
                        del_res = requests.delete(
                            f"{SUPABASE_URL}/rest/v1/8weeks_bookings?booking_id=eq.{bid}",
                            headers=delete_headers
                        )
                        if del_res.status_code in [200, 204]:
                            print(f"[DELETE] {bid} 削除（サロンボードに存在しない）", flush=True)
                    print(f"[DELETE] {len(to_delete)}件の古い予約を削除", flush=True)
                else:
                    print("[DELETE] 削除対象なし", flush=True)
        except Exception as e:
            print(f"[DELETE] 削除処理エラー: {e}", flush=True)
    
    # === 同一電話番号・同一日時の重複削除 ===
    # 次回予約(YF)とホットペッパー(BE)が重複した場合、次回予約(YF)を優先
    # 理由: ホットペッパー予約をキャンセル後、店舗で次回予約を入れるケースがある
    try:
        db_res = requests.get(
            f"{SUPABASE_URL}/rest/v1/8weeks_bookings?select=booking_id,phone,visit_datetime",
            headers=headers
        )
        if db_res.status_code == 200:
            db_bookings = db_res.json()
            seen = {}
            duplicates_to_delete = []
            for b in db_bookings:
                key = f"{b['phone']}_{b['visit_datetime']}"
                if key in seen:
                    # 重複発見: ホットペッパー(BE)を削除、次回予約(YF)を残す
                    existing = seen[key]
                    if b['booking_id'].startswith('BE') and existing.startswith('YF'):
                        duplicates_to_delete.append(b['booking_id'])
                    elif b['booking_id'].startswith('YF') and existing.startswith('BE'):
                        duplicates_to_delete.append(existing)
                        seen[key] = b['booking_id']
                else:
                    seen[key] = b['booking_id']
            
            if duplicates_to_delete:
                for bid in duplicates_to_delete:
                    del_res = requests.delete(
                        f"{SUPABASE_URL}/rest/v1/8weeks_bookings?booking_id=eq.{bid}",
                        headers=headers
                    )
                    if del_res.status_code in [200, 204]:
                        print(f"[重複削除] {bid}（ホットペッパー）を削除", flush=True)
                print(f"[重複削除] {len(duplicates_to_delete)}件削除完了", flush=True)
    except Exception as e:
        print(f"[重複削除] エラー: {e}", flush=True)
    
    # 成功したのでカウンターリセット
    reset_failure_count()
    
    print(f"\n[完了] {total_saved}件の予約を保存", flush=True)
    print(f"[{datetime.now(JST)}] 8週間予約スクレイピング（並列処理版）完了", flush=True)

if __name__ == "__main__":
    main()
