#!/usr/bin/env python3
"""SalonBoardからメニュー・金額をスクレイピングしてsalonboard_menusを更新"""

import os
import re
import requests
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_KEY')

def get_salonboard_menus():
    """既存のsalonboard_menusを取得"""
    headers = {'apikey': SUPABASE_KEY, 'Authorization': f'Bearer {SUPABASE_KEY}'}
    res = requests.get(f'{SUPABASE_URL}/rest/v1/salonboard_menus?select=id,name,duration,price&order=id.asc', headers=headers)
    return res.json() if res.status_code == 200 else []

def get_salon_menus():
    """salon_menus（金額あり）を取得"""
    headers = {'apikey': SUPABASE_KEY, 'Authorization': f'Bearer {SUPABASE_KEY}'}
    res = requests.get(f'{SUPABASE_URL}/rest/v1/salon_menus?select=name,price', headers=headers)
    return res.json() if res.status_code == 200 else []

def extract_price(price_str):
    """¥5,800形式から数値を抽出"""
    if not price_str:
        return 0
    match = re.search(r'[\d,]+', str(price_str).replace(',', ''))
    return int(match.group().replace(',', '')) if match else 0

def find_matching_price(menu_name, salon_menus):
    """類似メニューから金額を検索"""
    # 【次回】【全員】を除去
    clean_name = re.sub(r'【[^】]+】', '', menu_name).strip()
    
    # キーワードマッピング
    keywords_map = {
        'フラットラッシュ100本': ['フラットラッシュ100本'],
        'フラットラッシュ120本': ['フラットラッシュ120本'],
        'フラットラッシュ140本': ['フラットラッシュ140本'],
        'フラットラッシュつけ放題': ['フラットラッシュつけ放題'],
        'ブラウンニュアンスカラー120本': ['ブラウンニュアンスカラー120本', 'ブラウンニュアンス120本'],
        'ブラウンニュアンスカラー140本': ['ブラウンニュアンスカラー140本', 'ブラウンニュアンス140本'],
        'ブラウンニュアンスカラーつけ放題': ['ブラウンニュアンスカラーつけ放題'],
        'パリジェンヌラッシュリフト': ['パリジェンヌラッシュリフト', 'パリジェンヌ'],
        '上下パリジェンヌ': ['上下パリジェンヌ'],
        '上まつ毛パーマ': ['上まつ毛パーマ', '上まつげパーマ'],
        '上下まつ毛パーマ': ['上下まつ毛パーマ', '上下まつげパーマ'],
        '下まつげパーマ': ['下まつげパーマ', '下まつ毛パーマ'],
        '眉ワックス': ['眉ワックス', '3Dブロウワックス'],
        'パリエク120本': ['パリエク120本'],
        'パリエク140本': ['パリエク140本'],
        'パリエク付け放題': ['パリエク付け放題', 'パリエクつけ放題'],
        'リペア': ['リペア'],
    }
    
    for key, keywords in keywords_map.items():
        if key in clean_name:
            for keyword in keywords:
                for sm in salon_menus:
                    if keyword in sm.get('name', ''):
                        return extract_price(sm.get('price', ''))
    
    # 直接マッチ
    for sm in salon_menus:
        sm_clean = re.sub(r'【[^】]+】|《[^》]+》', '', sm.get('name', '')).strip()
        if clean_name in sm_clean or sm_clean in clean_name:
            return extract_price(sm.get('price', ''))
    
    return 0

def update_price(menu_id, price):
    """salonboard_menusの金額を更新"""
    headers = {'apikey': SUPABASE_KEY, 'Authorization': f'Bearer {SUPABASE_KEY}', 'Content-Type': 'application/json'}
    res = requests.patch(f'{SUPABASE_URL}/rest/v1/salonboard_menus?id=eq.{menu_id}', headers=headers, json={'price': price})
    return res.status_code == 204

def main():
    print(f"=== salonboard_menus 金額更新 ({datetime.now().strftime('%Y-%m-%d %H:%M:%S')}) ===")
    
    salonboard_menus = get_salonboard_menus()
    salon_menus = get_salon_menus()
    
    print(f"salonboard_menus: {len(salonboard_menus)}件")
    print(f"salon_menus: {len(salon_menus)}件")
    
    updated = 0
    not_found = []
    
    for menu in salonboard_menus:
        menu_id = menu['id']
        menu_name = menu['name']
        current_price = menu.get('price') or 0
        
        new_price = find_matching_price(menu_name, salon_menus)
        
        if new_price > 0:
            if new_price != current_price:
                if update_price(menu_id, new_price):
                    print(f"  ✅ {menu_name[:35]}... ¥{current_price} → ¥{new_price}")
                    updated += 1
                else:
                    print(f"  ❌ 更新失敗: {menu_name[:35]}...")
        else:
            not_found.append(menu_name)
    
    print(f"\n更新: {updated}件")
    if not_found:
        print(f"金額不明: {len(not_found)}件")
        for name in not_found[:5]:
            print(f"  - {name[:40]}...")

if __name__ == '__main__':
    main()
