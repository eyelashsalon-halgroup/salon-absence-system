#!/usr/bin/env python3
"""ブラウザでログインしてクッキーを保存"""
import json
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)
    context = browser.new_context()
    page = context.new_page()
    
    page.goto('https://salonboard.com/login/')
    print("ブラウザでログインしてください。完了したらEnterを押してください...")
    input()
    
    cookies = context.cookies()
    with open('session_cookies.json', 'w') as f:
        json.dump(cookies, f, indent=2)
    
    print(f"クッキー保存完了: {len(cookies)}個")
    browser.close()
