
#!/usr/bin/env python3

"""

SalonBoard画像認証突破テスト

2Captcha APIを使用したドラッグ&ドロップCAPTCHA解決

Railway対応: requestsのみ使用（Selenium不要）

"""

import os

import requests

import time

import json

import re

from dotenv import load_dotenv

load_dotenv()

# 2Captcha API（テスト用、実際のキーは環境変数から）

TWOCAPTCHA_API_KEY = os.getenv('TWOCAPTCHA_API_KEY', '')

def solve_captcha_with_2captcha(image_url, instruction):

    """

    2Captcha APIでCAPTCHAを解決

    https://2captcha.com/2captcha-api#coordinates

    """

    if not TWOCAPTCHA_API_KEY:

        print("⚠️ TWOCAPTCHA_API_KEY未設定")

        return None

    

    # 1. CAPTCHAを送信

    payload = {

        'key': TWOCAPTCHA_API_KEY,

        'method': 'base64',

        'coordinatescaptcha': 1,

        'body': image_url,  # base64エンコード画像

        'textinstructions': instruction,

        'json': 1

    }

    

    res = requests.post('https://2captcha.com/in.php', data=payload)

    result = res.json()

    

    if result.get('status') != 1:

        print(f"❌ CAPTCHA送信失敗: {result}")

        return None

    

    captcha_id = result.get('request')

    print(f"📤 CAPTCHA送信完了: ID={captcha_id}")

    

    # 2. 結果を取得（ポーリング）

    for _ in range(30):

        time.sleep(5)

        res = requests.get(f'https://2captcha.com/res.php?key={TWOCAPTCHA_API_KEY}&action=get&id={captcha_id}&json=1')

        result = res.json()

        

        if result.get('status') == 1:

            print(f"✅ CAPTCHA解決: {result.get('request')}")

            return result.get('request')

        elif result.get('request') != 'CAPCHA_NOT_READY':

            print(f"❌ CAPTCHA解決失敗: {result}")

            return None

    

    print("❌ タイムアウト")

    return None

def test_salonboard_login_with_session():

    """

    セッションベースのログインテスト

    （ブラウザ不要、requests使用）

    """

    session = requests.Session()

    session.headers.update({

        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'

    })

    

    # 1. ログインページ取得

    login_url = 'https://salonboard.com/login/'

    res = session.get(login_url)

    print(f"ログインページ: {res.status_code}")

    

    # 2. CAPTCHA画像の有無を確認

    if '画像認証' in res.text or 'captcha' in res.text.lower():

        print("⚠️ 画像認証が必要です")

        # CAPTCHAの詳細を解析...

        return False

    

    return True

if __name__ == '__main__':

    print("=== SalonBoard ログインテスト ===")

    print(f"2Captcha APIキー: {'設定済' if TWOCAPTCHA_API_KEY else '未設定'}")

    print()

    

    # セッションテスト

    test_salonboard_login_with_session()

