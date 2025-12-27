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


# スレッドセーフなロック
db_lock = threading.Lock()
result_lock = threading.Lock()

def scrape_date_range(worker_id, start_day, end_day, existing_cache, headers, today):
    """指定範囲の日付をスクレイピング（1ワーカー）"""
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
                    page.wait_for_timeout(500)
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
                    page.wait_for_timeout(500)
                
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
                        staff_name = re.sub(r'^\(指\)', '', staff_text).strip() if staff_text.startswith('(指)') else ''

                        
                        cached = existing_cache.get(booking_id, {})
                        menu = cached.get('menu', '')
                        phone = cached.get('phone', '')
                        
                        if not phone:
                            phone = get_phone_for_customer(customer_name, booking_id)
                        
                        bookings_list.append({
                            'booking_id': booking_id,
                            'customer_name': customer_name,
                            'visit_datetime': visit_datetime,
                            'staff': staff_name,
                            'menu': menu,
                            'phone': phone,
                            'status': '予約確定'
                        })
                    except:
                        continue
                
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
    page.wait_for_timeout(5000)
    
    try:
        page.fill('input[name="userId"]', login_id)
        page.fill('input[name="password"]', login_password)
        print(f"[LOGIN] ID/PW入力完了", flush=True)
        
        # ログインボタンをクリック
        btn = page.query_selector('a.common-CNCcommon__primaryBtn')
        if btn:
            btn.click()
            print(f"[LOGIN] ボタンクリック", flush=True)
        else:
            page.keyboard.press('Enter')
            print(f"[LOGIN] Enter押下", flush=True)
        
        # ページ遷移を待つ
        for i in range(30):
            page.wait_for_timeout(1000)
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

def main():
    print(f"[{datetime.now(JST)}] 8週間予約スクレイピング（並列処理版）開始", flush=True)
    
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
            f"{SUPABASE_URL}/rest/v1/8weeks_bookings?select=booking_id,menu,phone",
            headers=headers
        )
        if cache_res.status_code == 200:
            for item in cache_res.json():
                existing_cache[item['booking_id']] = {'menu': item.get('menu', ''), 'phone': item.get('phone', '')}
            print(f"[CACHE] 既存データ: {len(existing_cache)}件", flush=True)
    except Exception as e:
        print(f"[CACHE] キャッシュ取得エラー: {e}", flush=True)
    
    today = datetime.now(JST)
    all_bookings = []
    
    # 4分割で並列実行
    ranges = [(0, 14), (14, 28), (28, 42), (42, 56)]
    
    print("[PARALLEL] 4ワーカーで並列実行開始", flush=True)
    start_time = datetime.now(JST)
    
    with ThreadPoolExecutor(max_workers=4) as executor:
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
                print(f"[PARALLEL] Worker{worker_id+1} 完了: {len(bookings)}件", flush=True)
            except Exception as e:
                print(f"[PARALLEL] Worker{worker_id+1} 例外: {e}", flush=True)
    
    end_time = datetime.now(JST)
    elapsed = (end_time - start_time).total_seconds()
    print(f"[PARALLEL] 全ワーカー完了: 合計{len(all_bookings)}件 ({elapsed:.1f}秒)", flush=True)
    
    # DBに保存
    total_saved = 0
    if all_bookings:
        for booking in all_bookings:
            try:
                upsert_headers = headers.copy()
                upsert_headers["Prefer"] = "resolution=merge-duplicates"
                res = requests.post(
                    f"{SUPABASE_URL}/rest/v1/8weeks_bookings",
                    headers=upsert_headers,
                    json=booking
                )
                if res.status_code in [200, 201, 409]:
                    total_saved += 1
                else:
                    print(f"[DB] エラー: {res.status_code} - {res.text[:100]}", flush=True)
            except Exception as e:
                print(f"[DB] 保存エラー: {e}", flush=True)
        print(f"[DB] {total_saved}件保存完了", flush=True)
    
    # 成功したのでカウンターリセット
    reset_failure_count()
    
    print(f"\n[完了] {total_saved}件の予約を保存", flush=True)
    print(f"[{datetime.now(JST)}] 8週間予約スクレイピング（並列処理版）完了", flush=True)

if __name__ == "__main__":
    main()
