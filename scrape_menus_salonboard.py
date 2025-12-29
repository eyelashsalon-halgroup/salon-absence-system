#!/usr/bin/env python3
"""SalonBoardメニュー＋施術時間スクレイピング"""

import os
import re
import json
import requests
from datetime import datetime
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

SUPABASE_URL = os.environ.get('SUPABASE_URL', 'https://lsrbeugmqqqklywmvjjs.supabase.co')
SUPABASE_KEY = os.environ.get('SUPABASE_KEY', '')
SALONBOARD_LOGIN_ID = os.environ.get('SALONBOARD_LOGIN_ID', '')
SALONBOARD_LOGIN_PASSWORD = os.environ.get('SALONBOARD_LOGIN_PASSWORD', '')

# 除外パターン
EXCLUDE_PATTERNS = ['【インスタ割】', '【SNS広告', '【ご新規】オフ', '【新規】オフ']

# メニュー名変更マップ
NAME_CHANGES = {
    '【次回】ダメージレス上まつ毛パーマ': '【次回】上まつ毛パーマ',
    '【次回】下まつげパーマ(トリートメント付き)': '【次回】下まつげパーマ',
    '【全員】パリエク120本パリジェンヌ＆まつエク・エクステ': '【全員】パリエク120本',
    '【全員】パリエク140本パリジェンヌ＆まつエク・エクステ': '【全員】パリエク140本',
    '【全員】パリエクつけ放題パリジェンヌ＆まつエク・エクステ': '【全員】パリエクつけ放題',
    '【次回】パリエク120本パリジェンヌ＆まつエク・エクステ': '【次回】パリエク120本',
    '【次回】パリエク140本パリジェンヌ＆まつエク・エクステ': '【次回】パリエク140本',
    '【次回】パリエク付け放題パリジェンヌ＆まつエク・エクステ': '【次回】パリエク付け放題',
}

def parse_duration(text):
    """施術時間テキストを分に変換"""
    text = text.strip()
    if '5分単位' in text:
        return None
    hours = 0
    minutes = 0
    h_match = re.search(r'(\d+)時間', text)
    m_match = re.search(r'(\d+)分', text)
    if h_match:
        hours = int(h_match.group(1))
    if m_match:
        minutes = int(m_match.group(1))
    total = hours * 60 + minutes
    return total if total > 0 else None

def clean_name(name):
    """メニュー名から余分なテキストを削除"""
    name = re.sub(r'\s*[￥\\¥]\d+[\d,]*.*', '', name)
    name = re.sub(r'\s+\d+\.?\d*/40.*', '', name)
    name = re.sub(r'\s+削除.*', '', name)
    name = re.sub(r'<[^>]+>', '', name)
    name = re.sub(r'\(トリートメント付\)', '', name)
    name = re.sub(r'\(TR付\)', '', name)
    name = re.sub(r'\(SP・TR付\)', '', name)
    name = re.sub(r'\(アイシャンプー・トリートメント付き?\)', '', name)
    name = re.sub(r'\(コーティング・シャンプー・オフ込\)', '', name)
    name = re.sub(r'\(オフ別\)', '', name)
    name = re.sub(r'\(4週間以内 ?\)', '', name)
    name = re.sub(r'◇+', '', name)
    name = re.sub(r'　+', ' ', name)
    name = re.sub(r'\s+', ' ', name)
    name = name.strip()
    # 変更マップ適用
    if name in NAME_CHANGES:
        name = NAME_CHANGES[name]
    return name

def login_to_salonboard(page):
    """SalonBoardにログイン（scrape_8weeks_v4.pyと同じ方法）"""
    login_id = os.environ.get('SALONBOARD_LOGIN_ID', 'CD18317')
    login_password = os.environ.get('SALONBOARD_LOGIN_PASSWORD', 'Ne8T2Hhi!')
    
    print("[1/4] SalonBoardにログイン中...")
    page.goto('https://salonboard.com/login/', timeout=60000)
    page.wait_for_timeout(5000)
    
    page.fill('input[name="userId"]', login_id)
    page.fill('input[name="password"]', login_password)
    print("  ID/PW入力完了")
    
    btn = page.query_selector('a.common-CNCcommon__primaryBtn')
    if btn:
        btn.click()
        print("  ボタンクリック")
    else:
        page.keyboard.press('Enter')
        print("  Enter押下")
    
    for i in range(30):
        page.wait_for_timeout(1000)
        current_url = page.url
        if '/KLP/' in current_url or 'doLogin' not in current_url:
            print("  ✓ ログイン完了")
            return

def scrape_menus(page):
    """メニュー一覧をスクレイピング"""
    print("[2/4] メニュー管理画面を取得中...")
    page.goto("https://salonboard.com/CNK/draft/menuEdit/")
    page.wait_for_timeout(5000)
    
    html = page.content()
    soup = BeautifulSoup(html, 'html.parser')
    
    tables = soup.find_all('table')
    menus = []
    
    for table in tables:
        table_text = ' '.join(table.get_text().split())
        name_match = re.search(r'(【[^】]+】[^\n【]{3,80})', table_text)
        if not name_match:
            continue
        
        name = clean_name(name_match.group(1).strip())
        
        # 除外パターンチェック
        if any(p in name for p in EXCLUDE_PATTERNS):
            continue
        
        time_span = table.find('span', class_='jscConvertTimeOutput')
        if not time_span:
            continue
        
        duration_text = time_span.get_text().strip()
        duration = parse_duration(duration_text)
        if not duration:
            continue
        
        if not any(m['name'] == name for m in menus):
            menus.append({'name': name, 'duration': duration})
    
    print(f"  ✓ {len(menus)}件取得")
    return menus

def save_to_supabase(menus):
    """Supabaseに保存（UPSERT）"""
    print("[3/4] Supabaseに保存中...")
    headers = {
        'apikey': SUPABASE_KEY,
        'Authorization': f'Bearer {SUPABASE_KEY}',
        'Content-Type': 'application/json',
        'Prefer': 'resolution=merge-duplicates'
    }
    
    success = 0
    for m in menus:
        res = requests.post(
            f'{SUPABASE_URL}/rest/v1/salonboard_menus?on_conflict=name',
            headers=headers,
            json={'name': m['name'], 'duration': m['duration']}
        )
        if res.status_code in [200, 201]:
            success += 1
    
    print(f"  ✓ {success}/{len(menus)}件保存完了")
    return success

def main():
    print(f"\n{'='*50}")
    print(f"SalonBoardメニュースクレイピング")
    print(f"実行時刻: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*50}\n")
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()
        
        try:
            login_to_salonboard(page)
            menus = scrape_menus(page)
            save_to_supabase(menus)
            print(f"\n[4/4] 完了！ {len(menus)}件のメニューを更新しました\n")
        except Exception as e:
            print(f"\n[ERROR] {e}\n")
        finally:
            browser.close()

if __name__ == "__main__":
    main()
