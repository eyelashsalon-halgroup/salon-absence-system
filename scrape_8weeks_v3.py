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

print(f"[STARTUP] scrape_8weeks_v3.py 開始", flush=True)

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

def login_to_salonboard(page):
    login_id = os.environ.get('SALONBOARD_LOGIN_ID', 'CD18317')
    login_password = os.environ.get('SALONBOARD_LOGIN_PASSWORD', 'Ne8T2Hhi!')
    
    print(f"[LOGIN] ログインページにアクセス中...", flush=True)
    page.goto('https://salonboard.com/login/', timeout=60000)
    page.wait_for_timeout(5000)
    
    print(f"[LOGIN] 現在のURL: {page.url}", flush=True)
    print(f"[LOGIN] ページタイトル: {page.title()}", flush=True)
    
    # ID入力
    try:
        page.fill('input[name="userId"]', login_id)
        print(f"[LOGIN] ID入力成功", flush=True)
    except Exception as e:
        print(f"[LOGIN] ID入力失敗: {e}", flush=True)
        return False
    
    # パスワード入力
    try:
        page.fill('input[name="password"]', login_password)
        print(f"[LOGIN] パスワード入力成功", flush=True)
    except Exception as e:
        print(f"[LOGIN] パスワード入力失敗: {e}", flush=True)
        return False
    
    # ログインボタンクリック（JavaScript実行）
    try:
        print(f"[LOGIN] JavaScriptでdologin()を実行...", flush=True)
        page.evaluate("dologin(new Event('click'))")
        print(f"[LOGIN] dologin()実行成功", flush=True)
    except Exception as e:
        print(f"[LOGIN] dologin()失敗: {e}", flush=True)
        return False
    
    # ページ遷移を待つ（デバッグ強化版）
    try:
        for i in range(30):
            page.wait_for_timeout(1000)
            current_url = page.url
            print(f"[LOGIN] {i+1}秒後URL: {current_url}", flush=True)
            if '/KLP/' in current_url:
                print(f"[LOGIN] KLP到達成功！", flush=True)
                break
        else:
            print(f"[LOGIN] 30秒タイムアウト", flush=True)
            try:
                body = page.inner_text('body')[:500]
                print(f"[LOGIN] ページ内容: {body}", flush=True)
            except Exception as e2:
                print(f"[LOGIN] ページ内容取得失敗: {e2}", flush=True)
            return False
    except Exception as e:
        print(f"[LOGIN] エラー: {e}", flush=True)
        print(f"[LOGIN] 現在のURL: {page.url}", flush=True)
        return False
    
    print(f"[LOGIN] ログイン後URL: {page.url}", flush=True)
    return 'login' not in page.url.lower()

def main():
    print(f"[{datetime.now(JST)}] 8週間予約スクレイピング開始", flush=True)
    
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
    
   # 既存データをキャッシュ（メニュー再取得をスキップするため）
    existing_cache = {}
    try:
        cache_res = requests.get(
            f"{SUPABASE_URL}/rest/v1/8weeks_bookings?select=booking_id,menu,phone",
            headers=headers
        )
        if cache_res.status_code == 200:
            for item in cache_res.json():
                existing_cache[item['booking_id']] = {'menu': item.get('menu', ''), 'phone': item.get('phone', '')}
            print(f"[CACHE] 既存データ: {len(existing_cache)}件", flush=True)
    except Exception as e:
        print(f"[CACHE] キャッシュ取得エラー: {e}", flush=True)
    
    # 今回取得した予約IDを記録（最後に削除判定で使用）
    scraped_booking_ids = []
    
    today = datetime.now(JST)
    total_saved = 0
    
    try:
        with sync_playwright() as p:
            print("[OK] Playwright起動", flush=True)
            browser = p.chromium.launch(
                headless=True,
                args=[
                    '--disable-blink-features=AutomationControlled',
                    '--disable-dev-shm-usage',
                    '--no-sandbox',
                    '--disable-setuid-sandbox',
                    '--disable-infobars',
                    '--window-position=0,0',
                    '--ignore-certifcate-errors',
                    '--ignore-certifcate-errors-spki-list',
                ]
            )
            print("[OK] ブラウザ起動", flush=True)
            
            context = browser.new_context(
                user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                viewport={'width': 1920, 'height': 1080},
                locale='ja-JP',
                timezone_id='Asia/Tokyo',
                java_script_enabled=True,
                bypass_csp=True,
            )
            
            # Stealth: navigator.webdriverを隠す
            context.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
                Object.defineProperty(navigator, 'languages', {get: () => ['ja-JP', 'ja', 'en-US', 'en']});
                window.chrome = {runtime: {}};
            """)
            
            try:
                with open('session_cookies.json', 'r') as f:
                    cookies = json.load(f)
                context.add_cookies(cookies)
                print(f"[OK] クッキー読み込み: {len(cookies)}個", flush=True)
            except Exception as e:
                print(f"[WARN] クッキー読み込み失敗: {e}", flush=True)
            
            page = context.new_page()
              
            # リトライ用リスト
            retry_list = []
            
            # 8週間分（56日）をループ
            for day_offset in range(56):
                target_date = today + timedelta(days=day_offset)
                date_str = target_date.strftime('%Y%m%d')
                url = f'https://salonboard.com/KLP/reserve/reserveList/searchDate?date={date_str}'
                
                print(f"[{target_date.strftime('%Y-%m-%d')}] アクセス中...", flush=True)
                
                try:
                    page.goto(url, timeout=60000)
                    page.wait_for_timeout(2000)
                except Exception as e:
                    print(f"[{target_date.strftime('%Y-%m-%d')}] アクセスエラー、スキップ: {e}", flush=True)
                    continue
                
                # ログイン確認（初回のみ）
                if day_offset == 0 and ('login' in page.url.lower() or 'エラー' in page.title() or len(page.query_selector_all('table')) == 0):
                    print("[WARN] ログインが必要", flush=True)
                    if not login_to_salonboard(page):
                        print("[ERROR] ログイン失敗", flush=True)
                        browser.close()
                        return
                    
                    new_cookies = context.cookies()
                    with open('session_cookies.json', 'w') as f:
                        json.dump(new_cookies, f, indent=2, ensure_ascii=False)
                    print("[OK] ログイン成功、クッキー保存", flush=True)
                    
                    page.goto(url, timeout=60000)
                    page.wait_for_timeout(2000)
                
                # 予約一覧テーブルを特定
                reservation_table = None
                tables = page.query_selector_all("table")
                for table in tables:
                    header = table.query_selector("th#comingDate")
                    if header:
                        reservation_table = table
                        break
                
                if not reservation_table:
                    print(f"[{target_date.strftime('%Y-%m-%d')}] 予約一覧テーブルなし、スキップ", flush=True)
                    continue
                
                rows = reservation_table.query_selector_all('tbody tr')
                print(f"[DEBUG] 予約行数: {len(rows)}", flush=True)
                day_saved = 0
                
                # フェーズ1: 一覧ページから全データを抽出
                bookings_data = []
                for row in rows:
                    try:
                        cells = row.query_selector_all('td')
                        if len(cells) < 4:
                            continue
                        
                        reserve_link = cells[2].query_selector("a[href*='reserveId=']")
                        href = reserve_link.get_attribute("href") if reserve_link else ""
                        id_match = re.search(r'reserveId=([A-Z]{2}\d+)', href)
                        booking_id = id_match.group(1) if id_match else None
                        
                        if not booking_id:
                            continue
                        
                        status_text = cells[1].text_content().strip() if len(cells) > 1 else ""
                        if "受付待ち" not in status_text:
                            continue
                        
                        name_elem = cells[2].query_selector("p.wordBreak")
                        customer_name = name_elem.text_content().strip() if name_elem else ""
                        customer_name = re.sub(r'[★☆♪♡⭐️🦁]', '', customer_name).strip()
                        
                        time_cell = cells[0].text_content().strip() if len(cells) > 0 else ""
                        time_match = re.search(r'(\d{1,2}:\d{2})', time_cell)
                        time_only = time_match.group(1) if time_match else "00:00"
                        visit_datetime = f"{target_date.strftime('%Y-%m-%d')} {time_only}:00"
                        
                        staff_text = cells[3].text_content().strip() if len(cells) > 3 else ""
                        staff = re.sub(r'^\(指\)', '', staff_text).strip() if staff_text.startswith('(指)') else ''
                        
                        source = cells[4].text_content().strip() if len(cells) > 4 else ""
                        
                        if customer_name:
                            bookings_data.append({
                                'booking_id': booking_id,
                                'customer_name': customer_name,
                                'visit_datetime': visit_datetime,
                                'staff': staff,
                                'source': source,
                                'href': href
                            })
                    except Exception as e:
                        print(f"[ERROR] 抽出例外: {e}", flush=True)
                        continue
                
                # デバッグ: 取得した予約一覧を出力
                print(f"[DEBUG] 取得予約: {[b['customer_name'] for b in bookings_data]}", flush=True)
                
                # フェーズ2: 詳細ページからメニュー取得 → DB保存
                for item in bookings_data:
                    try:
                        scraped_booking_ids.append(item['booking_id'])
                        
                        # キャッシュにメニューがあればスキップ
                        duration = 60  # デフォルト値
                        phone = ''  # 電話番号初期化
                        cached_data = existing_cache.get(item['booking_id'], {})
                        cached_menu = cached_data.get('menu', '') if isinstance(cached_data, dict) else cached_data
                        cached_phone = cached_data.get('phone', '') if isinstance(cached_data, dict) else ''
                        if cached_menu and cached_phone:
                            menu = cached_menu
                            phone = cached_phone
                            print(f"[CACHE] {item['customer_name']} → {menu[:30]}", flush=True)
                        elif item['href']:
                            menu = ''
                            try:
                                detail_url = f"https://salonboard.com{item['href']}"
                                print(f"[DEBUG] 詳細ページアクセス: {detail_url}", flush=True)
                                page.goto(detail_url, timeout=15000)
                                page.wait_for_timeout(500)
                                menu_el = page.query_selector('th:has-text("メニュー") + td')
                                if not menu_el:
                                    menu_el = page.query_selector('td:has-text("【")')
                                if menu_el:
                                    menu = menu_el.inner_text().strip()[:100]
                                # 電話番号取得
                                phone = ''
                                try:
                                    phone_el = page.query_selector('th:has-text("電話番号") + td')
                                    if phone_el:
                                        phone = phone_el.inner_text().strip()
                                    if phone:
                                        print(f"[PHONE] {item['customer_name']} → {phone}", flush=True)
                                    else:
                                        print(f"[PHONE] {item['customer_name']} → 電話番号なし", flush=True)
                                except Exception as e:
                                    print(f"[PHONE] {item['customer_name']} → エラー: {e}", flush=True)
                                # 所要時間取得

                                try:
                                    hour_el = page.query_selector('#jsiRsvTermHour')
                                    min_el = page.query_selector('#jsiRsvTermMinute')
                                    if hour_el and min_el:
                                        h = int(hour_el.evaluate('el => el.value') or 0)
                                        m = int(min_el.evaluate('el => el.value') or 0)
                                        duration = h * 60 + m
                                        print(f'[DURATION] {item["customer_name"]} → {duration}分', flush=True)
                                except:
                                    pass
                                    print(f"[MENU] {item['customer_name']} → {menu[:30]}", flush=True)
                            except Exception as e:
                                current_url = page.url
                                print(f"[MENU] 取得スキップ: {item['customer_name']} - {e} (現在URL: {current_url})", flush=True)
                                retry_list.append(item)
                        else:
                            menu = ''
                        
                        data = {
                            'booking_id': item['booking_id'],
                            'customer_name': item['customer_name'],
                            'phone': phone if phone else get_phone_for_customer(item['customer_name'], item['booking_id']),
                            'visit_datetime': item['visit_datetime'],
                            'menu': menu,
                            'staff': item['staff'],
                            'status': 'confirmed',
                            'booking_source': item['source'],
                            'duration': duration
                        }
                        
                        res = requests.post(
                            f'{SUPABASE_URL}/rest/v1/8weeks_bookings?on_conflict=booking_id',
                            headers=headers,
                            json=data
                        )
                        
                        if res.status_code in [200, 201]:
                            total_saved += 1
                            day_saved += 1
                        else:
                            print(f"[ERROR] 保存失敗: {res.status_code}", flush=True)
                    except Exception as e:
                        print(f"[ERROR] 保存例外: {e}", flush=True)
                        continue
                
                print(f"[{target_date.strftime('%Y-%m-%d')}] {day_saved}件保存", flush=True)
            
            # === リトライ処理 ===
            if retry_list:
                print(f"\n[RETRY] {len(retry_list)}件のリトライ開始", flush=True)
                for item in retry_list:
                    if not item.get('href'):
                        continue
                    try:
                        detail_url = f"https://salonboard.com{item['href']}"
                        print(f"[RETRY] {item['customer_name']}", flush=True)
                        page.goto(detail_url, timeout=30000)
                        page.wait_for_timeout(1000)
                        
                        menu = ''
                        menu_el = page.query_selector('th:has-text("メニュー") + td')
                        if not menu_el:
                            menu_el = page.query_selector('td:has-text("【")')
                        if menu_el:
                            menu = menu_el.inner_text().strip()[:100]
                        
                        phone = ''
                        phone_el = page.query_selector('th:has-text("電話番号") + td a')
                        if phone_el:
                            phone = phone_el.inner_text().strip()
                            print(f"[RETRY][PHONE] {item['customer_name']} → {phone}", flush=True)
                        
                        if menu or phone:
                            data = {
                                'booking_id': item['booking_id'],
                                'customer_name': item['customer_name'],
                                'phone': phone if phone else get_phone_for_customer(item['customer_name'], item['booking_id']),
                                'visit_datetime': item['visit_datetime'],
                                'menu': menu,
                                'staff': item['staff'],
                                'status': 'confirmed',
                                'booking_source': item['source'],
                                'duration': 60
                            }
                            res = requests.post(
                                f'{SUPABASE_URL}/rest/v1/8weeks_bookings?on_conflict=booking_id',
                                headers=headers,
                                json=data
                            )
                            if res.status_code in [200, 201]:
                                print(f"[RETRY][OK] {item['customer_name']}", flush=True)
                    except Exception as e:
                        print(f"[RETRY][FAIL] {item['customer_name']} - {e}", flush=True)
            
            # === 空き枠をSupabaseに保存 ===
            print("\n[空き枠] 14日分の空き枠を取得・保存中...", flush=True)
            import math
            
            for day_offset in range(14):
                target_date = today + timedelta(days=day_offset)
                date_str = target_date.strftime('%Y%m%d')
                
                url = f'https://salonboard.com/KLP/schedule/salonSchedule/?date={date_str}'
                page.goto(url, timeout=60000)
                
                try:
                    page.wait_for_selector('.scheduleMainTableLine', timeout=15000)
                    page.wait_for_timeout(1000)
                except:
                    continue
                
                # スタッフリスト取得
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
                    
                    # Supabaseに保存
                    slot_data = {
                        'date': date_str,
                        'staff_id': staff_info['id'],
                        'staff_name': staff_info['name'],
                        'is_day_off': is_day_off,
                        'slots': available_slots,
                        'updated_at': datetime.now().isoformat()
                    }
                    
                    requests.post(
                        f'{SUPABASE_URL}/rest/v1/available_slots?on_conflict=date,staff_id',
                        headers={**headers, 'Prefer': 'resolution=merge-duplicates'},
                        json=slot_data
                    )
                
                print(f"[空き枠] {date_str} 完了", flush=True)
            
            print("[空き枠] 保存完了", flush=True)
            
            browser.close()
            
            # 今回取得していない予約を削除（キャンセル等）
            if scraped_booking_ids:
                try:
                    for old_id in existing_cache.keys():
                        if old_id not in scraped_booking_ids:
                            del_res = requests.delete(
                                f"{SUPABASE_URL}/rest/v1/8weeks_bookings?booking_id=eq.{old_id}",
                                headers=headers
                            )
                            if del_res.status_code in [200, 204]:
                                print(f"[DELETE] 削除: {old_id}", flush=True)
                except Exception as e:
                    print(f"[DELETE] 削除エラー: {e}", flush=True)
    except Exception as e:
        print(f"[ERROR] 致命的エラー: {e}", flush=True)
        import traceback
        traceback.print_exc()
        return
    
    print(f"\n[完了] {total_saved}件の予約を保存", flush=True)
    
    # 電話番号補完処理
    try:
        print("\n[電話番号補完] 開始...", flush=True)
        
        # customersテーブルから電話番号がNULLの人を取得
        customers_response = requests.get(
            f"{SUPABASE_URL}/rest/v1/customers?phone=is.null&line_user_id=not.is.null&select=id,name,line_user_id",
            headers=headers
        )
        customers_without_phone = customers_response.json() if customers_response.status_code == 200 else []
        
        updated_count = 0
        for customer in customers_without_phone:
            customer_name = customer.get('name', '')
            customer_id = customer.get('id')
            
            if not customer_name or not customer_id:
                continue
            
            # 8weeks_bookingsから電話番号を検索
            booking_response = requests.get(
                f"{SUPABASE_URL}/rest/v1/8weeks_bookings?customer_name=eq.{customer_name}&phone=not.is.null&select=phone&limit=1",
                headers=headers
            )
            
            if booking_response.status_code == 200:
                bookings = booking_response.json()
                if bookings and bookings[0].get('phone'):
                    phone = bookings[0]['phone']
                    
                    # customersテーブルを更新
                    update_response = requests.patch(
                        f"{SUPABASE_URL}/rest/v1/customers?id=eq.{customer_id}",
                        headers={**headers, 'Prefer': 'return=minimal'},
                        json={'phone': phone}
                    )
                    
                    if update_response.status_code in [200, 204]:
                        print(f"[電話番号補完] {customer_name} → {phone}", flush=True)
                        updated_count += 1
        
        print(f"[電話番号補完] {updated_count}件更新完了", flush=True)
    except Exception as e:
        print(f"[電話番号補完] エラー: {e}", flush=True)

if __name__ == "__main__":
    main()
