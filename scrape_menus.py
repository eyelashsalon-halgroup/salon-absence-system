#!/usr/bin/env python3
"""
ホットペッパービューティーからクーポン/メニュー一覧を取得
"""
import requests
from bs4 import BeautifulSoup
import os
import json

SUPABASE_URL = os.environ.get('SUPABASE_URL', 'https://lsrbeugmqqqklywmvjjs.supabase.co')
SUPABASE_KEY = os.environ.get('SUPABASE_KEY', '')

SALON_ID = 'slnH000537368'
BASE_URL = f'https://beauty.hotpepper.jp/kr/{SALON_ID}/coupon/'

def scrape_coupons():
    """クーポン一覧を取得"""
    all_coupons = []
    page = 1
    
    while True:
        url = BASE_URL if page == 1 else f'{BASE_URL}PN{page}.html'
        print(f"[INFO] ページ {page} 取得中: {url}")
        
        res = requests.get(url, headers={
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
        })
        
        if res.status_code != 200:
            print(f"[ERROR] ページ取得失敗: {res.status_code}")
            break
        
        soup = BeautifulSoup(res.text, 'html.parser')
        
        # クーポンテーブルを取得
        coupon_tables = soup.select('table.couponTable')
        
        if not coupon_tables:
            print(f"[INFO] ページ {page} にクーポンなし、終了")
            break
        
        for table in coupon_tables:
            try:
                # クーポンID
                coupon_id_tag = table.find_previous('a', id=lambda x: x and x.startswith('CP'))
                coupon_id = coupon_id_tag.get('id') if coupon_id_tag else None
                
                # クーポン名
                name_tag = table.select_one('p.couponMenuName')
                name = name_tag.get_text(strip=True) if name_tag else ''
                
                # 価格
                price_tag = table.select_one('p.couponMenuPrice')
                price = price_tag.get_text(strip=True) if price_tag else ''
                
                # カテゴリ
                category_tags = table.select('li.couponMenuIconGR05')
                categories = [c.get_text(strip=True) for c in category_tags]
                
                # 説明
                desc_tag = table.select_one('p.couponDescription')
                description = desc_tag.get_text(strip=True) if desc_tag else ''
                
                # 新規/再来
                label_tag = table.select_one('td.couponLabelCT02, td.couponLabelCT01, td.couponLabelCT03')
                coupon_type = label_tag.get_text(strip=True).replace('\n', '').replace(' ', '') if label_tag else ''
                
                if name:
                    all_coupons.append({
                        'coupon_id': coupon_id,
                        'name': name,
                        'price': price,
                        'categories': categories,
                        'description': description,
                        'coupon_type': coupon_type
                    })
                    print(f"  [OK] {name[:30]}... ({price})")
            except Exception as e:
                print(f"  [ERROR] クーポン解析エラー: {e}")
        
        # 次ページチェック
        next_link = soup.select_one('a.arrowPagingR')
        if not next_link:
            print(f"[INFO] 最終ページ到達")
            break
        
        page += 1
        if page > 10:  # 安全制限
            break
    
    print(f"\n[完了] {len(all_coupons)}件のクーポンを取得")
    return all_coupons

def save_to_supabase(coupons):
    """Supabaseに保存"""
    if not SUPABASE_KEY:
        print("[WARN] SUPABASE_KEY未設定、ローカル保存のみ")
        return
    
    headers = {
        'apikey': SUPABASE_KEY,
        'Authorization': f'Bearer {SUPABASE_KEY}',
        'Content-Type': 'application/json',
        'Prefer': 'resolution=merge-duplicates'
    }
    
    # 既存データ削除
    requests.delete(
        f'{SUPABASE_URL}/rest/v1/salon_menus?salon_id=eq.{SALON_ID}',
        headers=headers
    )
    
    # 新規保存
    for coupon in coupons:
        data = {
            'salon_id': SALON_ID,
            'coupon_id': coupon['coupon_id'],
            'name': coupon['name'],
            'price': coupon['price'],
            'categories': ','.join(coupon['categories']),
            'description': coupon['description'],
            'coupon_type': coupon['coupon_type']
        }
        res = requests.post(
            f'{SUPABASE_URL}/rest/v1/salon_menus',
            headers=headers,
            json=data
        )
        if res.status_code not in [200, 201]:
            print(f"[ERROR] 保存失敗: {coupon['name'][:20]}")
    
    print(f"[DB] {len(coupons)}件保存完了")

if __name__ == '__main__':
    coupons = scrape_coupons()
    
    # ローカルJSONにも保存
    with open('salon_menus.json', 'w', encoding='utf-8') as f:
        json.dump(coupons, f, ensure_ascii=False, indent=2)
    print("[FILE] salon_menus.json 保存完了")
    
    save_to_supabase(coupons)
