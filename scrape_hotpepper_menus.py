#!/usr/bin/env python3
"""ホットペッパービューティーからメニュー・金額をスクレイピング"""

import requests
from bs4 import BeautifulSoup
import re
import os
from dotenv import load_dotenv

load_dotenv()

STORE_ID = "H000537368"
BASE_URL = f"https://beauty.hotpepper.jp/CSP/kr/reserve/?storeId={STORE_ID}"

SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_KEY')

def scrape_menus():
    """ホットペッパーからメニュー一覧を取得"""
    headers = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
    }
    
    menus = []
    
    # クーポンページをスクレイピング
    for page in range(1, 3):  # 2ページ分
        url = f"https://beauty.hotpepper.jp/CSP/kr/reserve/?storeId={STORE_ID}&page={page}"
        print(f"Fetching: {url}")
        
        res = requests.get(url, headers=headers)
        if res.status_code != 200:
            print(f"Error: {res.status_code}")
            continue
            
        soup = BeautifulSoup(res.text, 'html.parser')
        
        # クーポンカードを取得
        coupon_cards = soup.select('.couponCard, .cpmBox, [class*="coupon"]')
        
        for card in coupon_cards:
            try:
                # メニュー名
                name_el = card.select_one('.couponName, .cpmName, h3, .ttl')
                if not name_el:
                    continue
                name = name_el.get_text(strip=True)
                
                # 金額
                price_el = card.select_one('.couponPrice, .price, .fs24, [class*="price"]')
                price = 0
                if price_el:
                    price_text = price_el.get_text(strip=True)
                    price_match = re.search(r'[\d,]+', price_text.replace(',', ''))
                    if price_match:
                        price = int(price_match.group().replace(',', ''))
                
                # 所要時間
                duration_el = card.select_one('.time, [class*="time"], [class*="minute"]')
                duration = 60
                if duration_el:
                    duration_text = duration_el.get_text(strip=True)
                    duration_match = re.search(r'(\d+)分', duration_text)
                    if duration_match:
                        duration = int(duration_match.group(1))
                
                if name and len(name) > 3:
                    menus.append({
                        'name': name[:200],
                        'price': price,
                        'duration': duration
                    })
                    print(f"  Found: {name[:50]}... ¥{price} ({duration}分)")
                    
            except Exception as e:
                print(f"  Error parsing card: {e}")
                continue
    
    return menus

def save_to_supabase(menus):
    """Supabaseに保存"""
    if not menus:
        print("No menus to save")
        return
        
    headers = {
        'apikey': SUPABASE_KEY,
        'Authorization': f'Bearer {SUPABASE_KEY}',
        'Content-Type': 'application/json',
        'Prefer': 'resolution=merge-duplicates'
    }
    
    for menu in menus:
        # 既存チェック
        check_res = requests.get(
            f"{SUPABASE_URL}/rest/v1/salonboard_menus?name=eq.{requests.utils.quote(menu['name'])}",
            headers=headers
        )
        
        if check_res.status_code == 200 and check_res.json():
            # 更新
            existing_id = check_res.json()[0]['id']
            update_res = requests.patch(
                f"{SUPABASE_URL}/rest/v1/salonboard_menus?id=eq.{existing_id}",
                headers=headers,
                json={'price': menu['price'], 'duration': menu['duration']}
            )
            print(f"Updated: {menu['name'][:30]}... ¥{menu['price']}")
        else:
            # 新規追加
            insert_res = requests.post(
                f"{SUPABASE_URL}/rest/v1/salonboard_menus",
                headers=headers,
                json=menu
            )
            print(f"Inserted: {menu['name'][:30]}... ¥{menu['price']}")

if __name__ == '__main__':
    print("=== ホットペッパービューティー メニュースクレイピング ===")
    menus = scrape_menus()
    print(f"\n取得メニュー数: {len(menus)}")
    
    if menus:
        print("\n=== Supabaseに保存 ===")
        save_to_supabase(menus)
    
    print("\n完了")
