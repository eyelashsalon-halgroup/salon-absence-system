# ヘルスチェック監視（別プロセスから呼び出し用）
import requests
import os

def check_and_notify():
    """Railwayヘルスチェック、失敗時にLINE通知"""
    KAMBARA_LINE_ID = "U9022782f05526cf7632902acaed0cb08"
    LINE_TOKEN = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN')
    
    try:
        res = requests.get("https://salon-absence-system-production.up.railway.app/health_check", timeout=10)
        if res.status_code != 200:
            send_alert(LINE_TOKEN, KAMBARA_LINE_ID, f"⚠️ Railway異常: ステータス {res.status_code}")
            return False
        return True
    except Exception as e:
        send_alert(LINE_TOKEN, KAMBARA_LINE_ID, f"🚨 Railwayダウン検知: {str(e)[:100]}")
        return False

def send_alert(token, user_id, message):
    requests.post(
        'https://api.line.me/v2/bot/message/push',
        headers={'Content-Type': 'application/json', 'Authorization': f'Bearer {token}'},
        json={'to': user_id, 'messages': [{'type': 'text', 'text': message}]}
    )
