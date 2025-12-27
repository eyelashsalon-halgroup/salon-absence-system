from playwright.sync_api import sync_playwright
import json
import os

os.environ['SUPABASE_URL'] = 'https://lsrbeugmqqqklywmvjjs.supabase.co'

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)
    context = browser.new_context()
    try:
        with open('session_cookies.json') as f:
            context.add_cookies(json.load(f))
    except: pass
    page = context.new_page()
    page.goto('https://salonboard.com/KLP/reserve/reserveList/searchDate?date=20251227')
    page.wait_for_timeout(3000)
    
    for table in page.query_selector_all('table'):
        if table.query_selector('th#comingDate'):
            rows = table.query_selector_all('tbody tr')
            print(f'rows: {len(rows)}')
            for row in rows[:3]:
                link = row.query_selector('a[href*="reserveId="]')
                cells = row.query_selector_all('td')
                print(f'cells: {len(cells)}, link: {link is not None}')
    browser.close()
