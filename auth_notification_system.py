from flask import Flask, request, render_template_string, redirect, url_for, session, jsonify, make_response, flash
import threading
import requests
import os
import json
from datetime import datetime, timezone, timedelta
from functools import wraps
from dotenv import load_dotenv
from collections import defaultdict
import time
import csv
from io import StringIO
from bs4 import BeautifulSoup
import schedule
import threading
from apscheduler.schedulers.background import BackgroundScheduler
# from supabase import create_client の行は削除

load_dotenv()

def clean_customer_name(text):
    """名前を正規化（スペース除去、★除去、余計な文字除去）"""
    import re
    # 改行以降を除去（予約IDなど）
    name = text.split("\n")[0].strip()
    # 除去パターン
    remove_patterns = [
        r"★+",
        r"です[。\.]*$",
        r"でーす[。\.]*$",
        r"よろしく.*$",
        r"お願い.*$",
        r"初めまして.*$",
        r"はじめまして.*$",
        r"こんにちは.*$",
        r"こんばんは.*$",
        r"おはよう.*$",
        r"[。、\.!！\?？]+$",
    ]
    for pattern in remove_patterns:
        name = re.sub(pattern, "", name)
    # スペース除去（半角・全角両方）
    name = re.sub(r"[\s　]+", "", name)
    return name.strip()

app = Flask(__name__)
app.secret_key = os.urandom(24)

# Supabase接続を追加（ここから）
SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_KEY')
# supabase = create_client の行は削除
# Supabase接続を追加（ここまで）

LINE_BOT_TOKEN = os.getenv('LINE_CHANNEL_ACCESS_TOKEN')
LINE_BOT_TOKEN_STAFF = os.getenv('LINE_CHANNEL_ACCESS_TOKEN_STAFF')
MAPPING_FILE = 'customer_mapping.json'
ABSENCE_FILE = 'absence_log.json'
MESSAGES_FILE = 'messages.json'

ADMIN_USERS = {
    'admin': 'admin123'
}

STAFF_USERS = {
    'kambara': {'password': 'kambara123', 'full_name': '神原', 'line_id': 'U3dafc1648cc64b066ca1c5b3f4a67f8e'},
    'saori': {'password': 'saori123', 'full_name': 'Saori', 'line_id': 'U1ad150fa84a287c095eb98186a8cdc45'}
}

staff_mapping = {
    "U3dafc1648cc64b066ca1c5b3f4a67f8e": {"name": "神原さん"},
    "U1ad150fa84a287c095eb98186a8cdc45": {"name": "Saoriさん"}
}

def load_messages():
    """メッセージをSupabaseから読み込む"""
    try:
        headers = {
            'apikey': SUPABASE_KEY,
            'Authorization': f'Bearer {SUPABASE_KEY}'
        }
        response = requests.get(
            f'{SUPABASE_URL}/rest/v1/message_templates?select=key,message',
            headers=headers
        )
        if response.status_code == 200:
            templates = response.json()
            return {t['key']: t['message'] for t in templates}
    except Exception as e:
        print(f"[ERROR] load_messages: {e}")
    # フォールバック
    return {
        "absence_request": "{staff_name}が本日欠勤となりました。",
        "substitute_confirmed": "{substitute_name}が出勤してくれることになりました。",
        "absence_confirmed": "欠勤申請を受け付けました。"
    }

def save_messages(messages):
    """メッセージをJSONファイルに保存"""
    with open(MESSAGES_FILE, 'w', encoding='utf-8') as f:
        json.dump(messages, f, ensure_ascii=False, indent=4)

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'logged_in' not in session:
            return redirect(url_for('login_page'))
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'logged_in' not in session:
            return redirect(url_for('login_page'))
        if session.get('role') != 'admin':
            return redirect(url_for('staff_absence'))
        return f(*args, **kwargs)
    return decorated_function

def load_mapping():
    try:
        headers = {
            'apikey': SUPABASE_KEY,
            'Authorization': f'Bearer {SUPABASE_KEY}'
        }
        response = requests.get(
            f'{SUPABASE_URL}/rest/v1/customers?select=*',
            headers=headers
        )
        
        if response.status_code == 200:
            result = {}
            for row in response.json():
                result[row['name']] = {
                    'user_id': row['line_user_id'],
                    'registered_at': row['registered_at']
                }
            return result
        return {}
    except Exception as e:
        print(f"Supabase読み込みエラー: {e}")
        return {}


def find_phone_from_bookings(name):
    """8weeks_bookingsテーブルから電話番号と正規化名を検索（名前完全一致）"""
    try:
        headers = {
            'apikey': SUPABASE_KEY,
            'Authorization': f'Bearer {SUPABASE_KEY}'
        }
        response = requests.get(f'{SUPABASE_URL}/rest/v1/8weeks_bookings?select=customer_name,phone,customer_number', headers=headers)
        if response.status_code == 200:
            norm_name = ''.join(name.split())
            for booking in response.json():
                booking_name = booking.get('customer_name', '')
                norm_booking = ''.join(booking_name.split())
                if norm_name == norm_booking:
                    phone = booking.get('phone')
                    customer_number = booking.get('customer_number')
                    return phone, customer_number, booking_name
        return None, None, None
    except Exception as e:
        print(f"電話番号検索エラー: {e}")
        return None, None, None

def save_mapping(customer_name, user_id):
    customer_name = clean_customer_name(customer_name)
    try:
        headers = {
            'apikey': SUPABASE_KEY,
            'Authorization': f'Bearer {SUPABASE_KEY}',
            'Content-Type': 'application/json'
        }
        
        # 既存チェック
        check_response = requests.get(
            f'{SUPABASE_URL}/rest/v1/customers?line_user_id=eq.{user_id}',
            headers=headers
        )
        
        if check_response.status_code == 200:
            existing_data = check_response.json()
            if len(existing_data) == 0:
                # 電話番号を検索
                phone, customer_number, normalized_name = find_phone_from_bookings(customer_name)
                if normalized_name:
                    customer_name = normalized_name
                # 新規登録
                data = {
                    'name': customer_name,
                    'line_user_id': user_id,
                    'registered_at': datetime.now().isoformat(),
                    'phone': phone,
                    'customer_number': customer_number
                }
                insert_response = requests.post(
                    f'{SUPABASE_URL}/rest/v1/customers',
                    headers=headers,
                    json=data
                )
                if insert_response.status_code == 201:
                    print(f"✓ {customer_name} をSupabaseに登録")
                    backup_customers()
                    return True
            else:
                # 既存ユーザーは更新しない（名前上書き防止）
                print(f"✓ 既存ユーザー: {existing_data[0].get('name', '')} (更新スキップ)")
                return True
    except Exception as e:
        print(f"Supabase保存エラー: {e}")
    return False

def load_absences():
    if os.path.exists(ABSENCE_FILE):
        with open(ABSENCE_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return []

def backup_customers():
    """顧客データをバックアップ"""
    try:
        mapping = load_mapping()
        backup_file = f'backup_customers_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json'
        with open(backup_file, 'w', encoding='utf-8') as f:
            json.dump(mapping, f, ensure_ascii=False, indent=2)
        print(f"✓ バックアップ作成: {backup_file}")
    except Exception as e:
        print(f"バックアップエラー: {e}")

def run_scheduler():
    """バックアップスケジューラーを実行"""
    while True:
        schedule.run_pending()
        time.sleep(3600)

def save_absence(staff_name, reason, details, alternative_date, absence_date=None):
    absences = load_absences()
    
    absences.append({
        "id": str(len(absences) + 1),
        "staff_name": staff_name,
        "reason": reason,
        "details": details,
        "alternative_date": alternative_date,
        "absence_date": absence_date or datetime.now().strftime("%Y-%m-%d"),
        "submitted_at": datetime.now().isoformat(),
        "status": "pending"
    })
    
    with open(ABSENCE_FILE, 'w', encoding='utf-8') as f:
        json.dump(absences, f, ensure_ascii=False, indent=2)

def group_absences_by_month(absences):
    grouped = defaultdict(list)
    for absence in absences:
        month_key = absence['submitted_at'][:7]
        grouped[month_key].append(absence)
    return dict(sorted(grouped.items(), reverse=True))

def get_full_name(username):
    if username in STAFF_USERS:
        return STAFF_USERS[username]['full_name']
    return username

def send_line_message(user_id, message, token=None, max_retries=3):
    if token is None:
        token = LINE_BOT_TOKEN
    """LINE送信（リトライ＋エラーログ機能付き）"""
    # テストモード：実際に送信しない
    if os.getenv("TEST_MODE", "false").lower() == "true":
        print(f"[テストモード] {user_id[:8]}... → {message[:30]}...")
        return True
    
    if not token:
        print("[エラー] LINE_BOT_TOKENが設定されていません")
        return False
    
    headers = {
        'Authorization': f'Bearer {token}',
        'Content-Type': 'application/json'
    }
    data = {
        'to': user_id,
        'messages': [{'type': 'text', 'text': message}]
    }
    
    for attempt in range(max_retries):
        try:
            response = requests.post(
                'https://api.line.me/v2/bot/message/push',
                headers=headers,
                json=data,
                timeout=10
            )
            
            if response.status_code == 200:
                if attempt > 0:
                    print(f"[成功] {attempt + 1}回目の試行で送信成功")
                return True
            else:
                print(f"[警告] LINE API エラー: {response.status_code} - {response.text}")
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)  # 指数バックオフ: 1秒、2秒、4秒
                    
        except requests.exceptions.Timeout:
            print(f"[エラー] タイムアウト (試行 {attempt + 1}/{max_retries})")
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)
                
        except requests.exceptions.RequestException as e:
            print(f"[エラー] リクエスト失敗 (試行 {attempt + 1}/{max_retries}): {str(e)}")
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)
                
        except Exception as e:
            print(f"[エラー] 予期しないエラー: {str(e)}")
            return False
    
    print(f"[失敗] {max_retries}回の試行後も送信失敗")
    return False


def notify_shop_booking_change(customer_name, old_datetime, new_datetime, staff_name=""):
    """予約変更を店舗LINEに通知"""
    message = f"""【予約変更通知】
お客様: {customer_name}
変更前: {old_datetime}
変更後: {new_datetime}
担当: {staff_name}

※お客様がLIFFから変更しました"""
    
    # 管理者に通知
    admin_line_id = os.getenv('ADMIN_LINE_USER_ID')
    if admin_line_id:
        send_line_message(admin_line_id, message, LINE_BOT_TOKEN_STAFF)

@app.route('/')
def index():
    return redirect(url_for('login_page'))

@app.route('/login', methods=['GET'])
def login_page():
    template = '''
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>スタッフ管理システム</title>
        <style>
            body {
                margin: 0;
                padding: 0;
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
                background: #f5f5f5;
            }
            .container {
                max-width: 600px;
                margin: 0 auto;
                padding: 20px;
            }
            .header {
                background: linear-gradient(135deg, #6b5b47 0%, #8b7355 100%);
                color: white;
                padding: 40px 20px;
                text-align: center;
                border-radius: 10px 10px 0 0;
            }
            .login-box {
                background: white;
                border-radius: 0 0 10px 10px;
                padding: 30px;
            }
            .tabs {
                display: flex;
                border-bottom: 2px solid #e0e0e0;
                margin-bottom: 30px;
            }
            .tab {
                flex: 1;
                padding: 15px;
                text-align: center;
                border-bottom: 3px solid transparent;
            }
            .tab.active {
                border-bottom-color: #6b5b47;
                font-weight: bold;
                color: #333;
            }
            .tab.disabled {
                color: #ccc;
                cursor: not-allowed;
            }
            .form-group {
                margin-bottom: 20px;
            }
            label {
                display: block;
                margin-bottom: 8px;
                font-weight: 500;
            }
            input {
                width: 100%;
                padding: 12px;
                border: 1px solid #ddd;
                border-radius: 6px;
                font-size: 16px;
                box-sizing: border-box;
            }
            .login-btn {
                width: 100%;
                padding: 15px;
                background: #6b5b47;
                color: white;
                border: none;
                border-radius: 6px;
                font-size: 16px;
                font-weight: bold;
                cursor: pointer;
            }
            .login-btn:hover {
                background: #8b7355;
            }
            .error {
                color: #d32f2f;
                margin-bottom: 15px;
                padding: 10px;
                background: #ffebee;
                border-radius: 4px;
            }
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1>STAFF CONNECT</h1>
                <p>スムーズなシフト調整を</p>
            </div>
            <div class="login-box">
                <div class="tabs">
                    <div class="tab active">ログイン</div>
                    <div class="tab disabled">新規登録</div>
                    <div class="tab disabled">一覧</div>
                    <div class="tab disabled">パスワード変更</div>
                </div>
                
                {% if error %}
                <div class="error">{{ error }}</div>
                {% endif %}
                
                <form method="POST" action="{{ url_for('login_action') }}">
                    <div class="form-group">
                        <label>ID</label>
                        <input type="text" name="username" required>
                    </div>
                    <div class="form-group">
                        <label>パスワード</label>
                        <input type="password" name="password" required>
                    </div>
                    <button type="submit" class="login-btn">ログイン</button>
                </form>
            </div>
        </div>
    </body>
    </html>
    '''
    error = request.args.get('error')
    return render_template_string(template, error=error)

@app.route('/login', methods=['POST'])
def login_action():
    username = request.form.get('username')
    password = request.form.get('password')
    
    if username in ADMIN_USERS and ADMIN_USERS[username] == password:
        session['logged_in'] = True
        session['username'] = username
        session['role'] = 'admin'
        return redirect(url_for('admin'))
    
    if username in STAFF_USERS and STAFF_USERS[username]['password'] == password:
        session['logged_in'] = True
        session['username'] = username
        session['role'] = 'staff'
        return redirect(url_for('staff_absence'))
    
    return redirect(url_for('login_page', error='IDまたはパスワードが正しくありません'))

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login_page'))

@app.route('/staff/absence')
@login_required
def staff_absence():
    if session.get('role') != 'staff':
        return redirect(url_for('admin'))
    
    template = '''
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>欠勤申請</title>
        <style>
            body { font-family: Arial; padding: 20px; background: #f5f5f5; margin: 0; }
            .container { max-width: 600px; margin: 0 auto; }
            .header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; }
            .content { background: white; padding: 30px; border-radius: 8px; }
            .form-group { margin-bottom: 25px; }
            label { display: block; margin-bottom: 8px; font-weight: 600; color: #333; }
            select, textarea, input { 
                width: 100%;
                padding: 12px;
                border: 1px solid #ddd;
                border-radius: 6px;
                font-family: inherit;
                font-size: 14px;
                box-sizing: border-box;
            }
            textarea {
                resize: vertical;
                min-height: 80px;
            }
            .submit-btn { 
                width: 100%;
                padding: 15px;
                background: #6b5b47;
                color: white;
                border: none;
                border-radius: 6px;
                cursor: pointer;
                font-size: 16px;
                font-weight: bold;
            }
            .submit-btn:hover {
                background: #8b7355;
            }
            .btn { 
                padding: 10px 20px;
                color: white;
                text-decoration: none;
                border-radius: 6px;
                margin-left: 10px;
            }
            .history-btn {
                background: #4caf50;
            }
            .history-btn:hover {
                background: #45a049;
            }
            .logout-btn { 
                background: #d32f2f;
            }
            .logout-btn:hover {
                background: #b71c1c;
            }
            .note {
                font-size: 12px;
                color: #666;
                margin-top: 5px;
            }
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1>欠勤申請</h1>
                <div>
                    <a href="{{ url_for('staff_my_absences') }}" class="btn history-btn">自分の申請履歴</a>
                    <a href="{{ url_for('logout') }}" class="btn logout-btn">ログアウト</a>
                </div>
            </div>
            
            <div class="content">
                <form method="POST" action="{{ url_for('confirm_absence') }}">
                    <div class="form-group">
                        <label>欠勤日 <span style="color: #d32f2f;">*</span></label>
                        <input type="date" name="absence_date" required style="width: 100%; padding: 12px; border: 1px solid #ddd; border-radius: 6px; font-size: 16px; margin-bottom: 20px;">
                    </div>
                    <div class="form-group">
                        <label>欠勤理由 <span style="color: #d32f2f;">*</span></label>
                        <select name="reason" required>
                            <option value="">選択してください</option>
                            <option value="体調不良">体調不良</option>
                            <option value="育児・介護の急用">育児・介護の急用</option>
                            <option value="冠婚葬祭（忌引）">冠婚葬祭（忌引）</option>
                            <option value="交通遅延・災害">交通遅延・災害</option>
                            <option value="家庭の事情">家庭の事情</option>
                            <option value="その他">その他</option>
                        </select>
                    </div>
                    
                    <div class="form-group">
                        <label>状況説明 <span style="color: #d32f2f;">*</span></label>
                        <textarea name="details" required placeholder="簡潔に状況をお知らせください（1-2行程度）"></textarea>
                    </div>
                    
                    <div class="form-group">
                        <label>代替可能日時（任意）</label>
                        <input type="text" name="alternative_date" placeholder="例: 明日以降であれば出勤可能">
                        <div class="note">代わりに出勤できる日があれば記入してください</div>
                    </div>
                    
                    <button type="submit" class="submit-btn">確認画面へ</button>
                </form>
            </div>
        </div>
    </body>
    </html>
    '''
    return render_template_string(template)

@app.route('/confirm_absence', methods=['POST'])
@login_required
def confirm_absence():
    if session.get('role') != 'staff':
        return redirect(url_for('admin'))
    
    reason = request.form.get('reason')
    details = request.form.get('details')
    alternative_date = request.form.get('alternative_date', '')
    
    template = '''
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>送信確認</title>
        <style>
            body { font-family: Arial; padding: 20px; background: #f5f5f5; margin: 0; }
            .container { max-width: 600px; margin: 0 auto; }
            .header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; }
            .content { background: white; padding: 30px; border-radius: 8px; }
            h2 { color: #333; margin-bottom: 30px; text-align: center; }
            .confirm-item { margin-bottom: 20px; padding: 15px; background: #f5f5f5; border-radius: 6px; }
            .confirm-label { font-weight: 600; color: #666; margin-bottom: 5px; }
            .confirm-value { color: #333; }
            .buttons { display: flex; gap: 15px; margin-top: 30px; }
            .btn { 
                flex: 1;
                padding: 15px;
                border: none;
                border-radius: 6px;
                cursor: pointer;
                font-size: 16px;
                font-weight: bold;
                text-align: center;
                text-decoration: none;
                display: block;
            }
            .btn-submit {
                background: #6b5b47;
                color: white;
            }
            .btn-submit:hover {
                background: #8b7355;
            }
            .btn-back {
                background: #e0e0e0;
                color: #333;
            }
            .btn-back:hover {
                background: #d0d0d0;
            }
            .logout-btn { 
                background: #d32f2f;
                padding: 10px 20px;
                color: white;
                text-decoration: none;
                border-radius: 6px;
            }
            .logout-btn:hover {
                background: #b71c1c;
            }
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1>送信確認</h1>
                <a href="{{ url_for('logout') }}" class="logout-btn">ログアウト</a>
            </div>
            
            <div class="content">
                <h2>この内容で送信しますか？</h2>
                <p style="color: #ff9800; background: #fff3e0; padding: 12px; border-radius: 6px; margin: 20px 0; text-align: center;">
                    ⚠️ 送信すると全スタッフに通知が送られます ⚠️
                </p>
                
                <div class="confirm-item">
                    <div class="confirm-label">欠勤理由</div>
                    <div class="confirm-value">{{ reason }}</div>
                </div>
                
                <div class="confirm-item">
                    <div class="confirm-label">状況説明</div>
                    <div class="confirm-value">{{ details }}</div>
                </div>
                
                {% if alternative_date %}
                <div class="confirm-item">
                    <div class="confirm-label">代替可能日時</div>
                    <div class="confirm-value">{{ alternative_date }}</div>
                </div>
                {% endif %}
                
                <form method="POST" action="{{ url_for('submit_absence') }}">
                    <input type="hidden" name="reason" value="{{ reason }}">
                    <input type="hidden" name="details" value="{{ details }}">
                    <input type="hidden" name="alternative_date" value="{{ alternative_date }}">
                    
                    <div class="buttons">
                        <a href="{{ url_for('staff_absence') }}" class="btn btn-back">戻る</a>
                        <button type="submit" class="btn btn-submit">送信</button>
                    </div>
                </form>
            </div>
        </div>
    </body>
    </html>
    '''
    return render_template_string(template, reason=reason, details=details, alternative_date=alternative_date)

@app.route('/submit_absence', methods=['POST'])
@login_required
def submit_absence():
    if session.get('role') != 'staff':
        return redirect(url_for('admin'))
    
    staff_name = session.get('username')
    reason = request.form.get('reason')
    details = request.form.get('details')
    alternative_date = request.form.get('alternative_date', '')
    
    absence_date = request.form.get('absence_date', datetime.now().strftime("%Y-%m-%d"))
    save_absence(staff_name, reason, details, alternative_date, absence_date)
    
    # メッセージを動的に読み込む
    MESSAGES = load_messages()
    
    full_name = get_full_name(staff_name)
    
    # LINE通知を非同期で送信（高速化）
    def send_notifications():
        LINE_USER_ID_HAL = os.getenv('LINE_USER_ID_HAL')
        if LINE_USER_ID_HAL:
            admin_message = f"【欠勤申請】\n{full_name}から欠勤申請がありました。\n\n欠勤日: {absence_date}\n理由: {reason}\n詳細: {details}\n\n管理画面で承認してください。\nhttps://salon-absence-system-production.up.railway.app/admin/absences"
            send_line_message(LINE_USER_ID_HAL, admin_message, LINE_BOT_TOKEN_STAFF)
        
        absence_message = MESSAGES["absence_request"].format(staff_name=full_name)
        for username, info in STAFF_USERS.items():
            if username != staff_name:
                send_line_message(info['line_id'], absence_message, LINE_BOT_TOKEN_STAFF)
        
        confirmation_message = MESSAGES["absence_confirmed"].format(reason=reason, details=details)
        send_line_message(STAFF_USERS[staff_name]['line_id'], confirmation_message, LINE_BOT_TOKEN_STAFF)
    
    threading.Thread(target=send_notifications).start()
    
    return redirect(url_for('absence_success'))

@app.route('/absence/success')
@login_required
def absence_success():
    template = '''
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>送信完了</title>
        <style>
            body { font-family: Arial; padding: 20px; background: #f5f5f5; margin: 0; }
            .container { max-width: 600px; margin: 0 auto; }
            .content { background: white; padding: 40px; border-radius: 8px; text-align: center; }
            .success-icon { font-size: 48px; color: #4caf50; margin-bottom: 20px; }
            h2 { color: #333; margin-bottom: 15px; }
            p { color: #666; margin-bottom: 30px; line-height: 1.6; }
            .buttons { display: flex; gap: 15px; justify-content: center; }
            .btn { 
                display: inline-block;
                padding: 12px 32px;
                color: white;
                text-decoration: none;
                border-radius: 6px;
                font-weight: bold;
            }
            .btn-primary {
                background: #6b5b47;
            }
            .btn-primary:hover {
                background: #8b7355;
            }
            .btn-secondary {
                background: #4caf50;  # 緑
            }
            .btn-secondary:hover {
                background: #45a049;
            }
        </style>
    </head>
    <body>
        <div class="container">
            <div class="content">
                <div class="success-icon">✓</div>
                <h2>欠勤申請を受け付けました</h2>
                <p>
                    他のスタッフおよびご自身のLINEに通知が送信されました。<br>
                    ご連絡ありがとうございます。
                </p>
                <div class="buttons">
                    <a href="{{ url_for('staff_my_absences') }}" class="btn btn-secondary">自分の申請履歴</a>
                    <a href="{{ url_for('logout') }}" class="btn btn-primary">ログアウト</a>
                </div>
            </div>
        </div>
    </body>
    </html>
    '''
    return render_template_string(template)

@app.route('/staff/my_absences')
@login_required
def staff_my_absences():
    if session.get('role') != 'staff':
        return redirect(url_for('admin'))
    
    staff_name = session.get('username')
    absences = load_absences()
    
    # 自分の申請のみフィルタリング
    my_absences = [a for a in absences if a.get('staff_name') == staff_name]
    my_absences.reverse()  # 新しい順
    
    template = '''
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>自分の申請履歴</title>
        <style>
            body { font-family: Arial; padding: 20px; background: #f5f5f5; margin: 0; }
            .container { max-width: 800px; margin: 0 auto; }
            .header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; }
            .content { background: white; padding: 30px; border-radius: 8px; }
            .stats { background: #e3f2fd; padding: 20px; border-radius: 8px; margin-bottom: 30px; text-align: center; }
            .stats-number { font-size: 48px; font-weight: bold; color: #1976d2; }
            .stats-label { color: #666; margin-top: 10px; }
            table { width: 100%; border-collapse: collapse; }
            th, td { padding: 12px; text-align: left; border-bottom: 1px solid #e0e0e0; }
            th { background: #f5f5f5; font-weight: bold; }
            .reason-badge { 
                background: #ffebee; 
                color: #d32f2f; 
                padding: 4px 8px; 
                border-radius: 4px; 
                font-size: 12px;
                font-weight: 500;
            }
            .btn { 
                padding: 12px 32px;
                color: white;
                text-decoration: none;
                border-radius: 6px;
                font-weight: bold;
            }
            .btn-back {
                background: #6b5b47;
            }
            .btn-back:hover {
                background: #8b7355;
            }
            .logout-btn { 
                background: #d32f2f;
            }
            .logout-btn:hover {
                background: #b71c1c;
            }
            .empty-message {
                text-align: center;
                color: #999;
                padding: 40px 0;
            }
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1>自分の申請履歴</h1>
                <div>
                    <a href="{{ url_for('staff_absence') }}" class="btn btn-back">新規申請</a>
                    <a href="{{ url_for('logout') }}" class="btn logout-btn">ログアウト</a>
                </div>
            </div>
            
            <div class="content">
                <div class="stats">
                    <div class="stats-number">{{ my_absences|length }}</div>
                    <div class="stats-label">合計申請回数</div>
                </div>
                
                {% if my_absences %}
                <table>
                    <tr>
                        <th>申請日時</th>
                        <th>欠勤理由</th>
                        <th>状況説明</th>
                        <th>代替可能日時</th>
                    </tr>
                    {% for absence in my_absences %}
                    <tr>
                        <td>{{ absence.submitted_at[:10] }} {{ absence.submitted_at[11:16] }}</td>
                        <td><span class="reason-badge">{{ absence.reason }}</span></td>
                        <td>{{ absence.details }}</td>
                        <td>{{ absence.alternative_date if absence.alternative_date else '-' }}</td>
                    </tr>
                    {% endfor %}
                </table>
                {% else %}
                <div class="empty-message">まだ申請はありません</div>
                {% endif %}
            </div>
        </div>
    </body>
    </html>
    '''
    return render_template_string(template, my_absences=my_absences)


@app.route('/admin/absences')
@admin_required
def admin_absences():
    absences = load_absences()
    pending = [a for a in absences if a.get('status') == 'pending']
    
    template = """
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>欠勤承認</title>
        <style>
            body { font-family: Arial; padding: 20px; background: #f5f5f5; }
            .container { max-width: 800px; margin: 0 auto; }
            .header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; }
            .card { background: white; padding: 20px; border-radius: 8px; margin-bottom: 15px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
            .card h3 { margin: 0 0 10px 0; color: #333; }
            .card p { margin: 5px 0; color: #666; }
            .btn { padding: 10px 20px; border: none; border-radius: 6px; cursor: pointer; font-weight: bold; }
            .btn-approve { background: #4caf50; color: white; }
            .btn-approve:hover { background: #45a049; }
            .btn-back { background: #6b5b47; color: white; text-decoration: none; }
            .empty { text-align: center; color: #999; padding: 40px; }
        </style>
    </head>
    <body>
        <div class="container">
            {% with messages = get_flashed_messages(with_categories=true) %}
                {% if messages %}
                    {% for category, message in messages %}
                        <div style="padding: 15px; margin-bottom: 20px; border-radius: 8px; 
                            {% if category == 'success' %}background: #d4edda; color: #155724;
                            {% elif category == 'warning' %}background: #fff3cd; color: #856404;
                            {% else %}background: #f8d7da; color: #721c24;{% endif %}">
                            {{ message }}
                        </div>
                    {% endfor %}
                {% endif %}
            {% endwith %}
            <div class="header">
                <h1>欠勤承認待ち</h1>
                <a href="/admin" class="btn btn-back">管理画面に戻る</a>
            </div>
            {% if pending %}
                {% for absence in pending %}
                <div class="card">
                    <h3>{{ absence.staff_name }}</h3>
                    <p><strong>欠勤日:</strong> {{ absence.absence_date }}</p>
                    <p><strong>理由:</strong> {{ absence.reason }}</p>
                    <p><strong>詳細:</strong> {{ absence.details }}</p>
                    <p><strong>申請日時:</strong> {{ absence.submitted_at }}</p>
                    <form method="POST" action="/admin/approve_absence" style="margin-top: 15px;">
                        <input type="hidden" name="absence_id" value="{{ absence.id }}">
                        <button type="submit" class="btn btn-approve">承認して顧客にLINE通知</button>
                    </form>
                </div>
                {% endfor %}
            {% else %}
                <div class="card empty">承認待ちの欠勤申請はありません</div>
            {% endif %}
        </div>
    </body>
    </html>
    """
    return render_template_string(template, pending=pending)

@app.route('/admin/approve_absence', methods=['POST'])
@admin_required
def approve_absence():
    absence_id = request.form.get('absence_id')
    absences = load_absences()
    
    target_absence = None
    for absence in absences:
        if absence.get('id') == absence_id:
            absence['status'] = 'approved'
            target_absence = absence
            break
    
    with open(ABSENCE_FILE, 'w', encoding='utf-8') as f:
        json.dump(absences, f, ensure_ascii=False, indent=2)
    
    if target_absence:
        absence_date = target_absence.get('absence_date')
        staff_name = target_absence.get('staff_name')
        
        # 該当日の予約顧客を8weeks_bookingsから取得
        try:
            headers = {
                'apikey': os.getenv('SUPABASE_KEY'),
                'Authorization': f"Bearer {os.getenv('SUPABASE_KEY')}"
            }
            response = requests.get(
                f"{os.getenv('SUPABASE_URL')}/rest/v1/8weeks_bookings?visit_datetime=like.{absence_date}*&select=customer_name,phone,visit_datetime,menu",
                headers=headers
            )
            bookings = response.json() if response.status_code == 200 else []
            
            # 顧客にLINE通知
            notified_count = 0
            for booking in bookings:
                customer_name = booking.get('customer_name', '').replace(' ', '')
                
                # customersテーブルからline_user_idを取得
                cust_response = requests.get(
                    f"{os.getenv('SUPABASE_URL')}/rest/v1/customers?select=line_user_id,name",
                    headers=headers
                )
                customers = cust_response.json() if cust_response.status_code == 200 else []
                
                for cust in customers:
                    cust_name = cust.get('name', '').replace(' ', '')
                    if cust_name == customer_name and cust.get('line_user_id'):
                        message = f"【重要】ご予約日程変更のお願い\n\n{booking.get('visit_datetime', '')[:10]}のご予約について、担当スタッフの都合により日程変更をお願いしたくご連絡いたしました。\n\n大変申し訳ございませんが、ご都合の良い日時をお知らせください。\n\neyelashsalon HAL"
                        # [DISABLED] send_line_message(cust.get('line_user_id'), message, LINE_BOT_TOKEN_STAFF)
                        # [TEST] 神原良祐にのみテスト送信
                        TEST_LINE_ID = "U9022782f05526cf7632902acaed0cb08"
                        test_message = f"[テスト通知]\n顧客: {cust_name}\n予約日: {booking.get('visit_datetime', '')[:10]}\n\n※実際の顧客には送信されていません"
                        send_line_message(TEST_LINE_ID, test_message, LINE_BOT_TOKEN_STAFF)
                        print(f"[TEST] 神原にテスト送信: {cust_name}", flush=True)
                        notified_count += 1
                        break
            
            flash(f'承認完了。{notified_count}名の顧客にLINE通知を送信しました。', 'success')
        except Exception as e:
            flash(f'承認完了。顧客通知でエラー: {str(e)}', 'warning')
    
    return redirect('/admin/absences')


@app.route('/admin')
@admin_required
def admin():
    # メッセージを動的に読み込む
    MESSAGES = load_messages()
    
    # 統計情報を計算
    mapping = load_mapping()
    customer_count = len(mapping)
    
    absences = load_absences()
    total_absences = len(absences)
    
    # 今月の欠勤申請数
    current_month = datetime.now().strftime("%Y年%m月")
    monthly_absences = sum(1 for a in absences if a.get("submitted_at", "").startswith(datetime.now().strftime("%Y-%m")))
    
    template = '''
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>メッセージ管理</title>
        <style>
            body { font-family: Arial; padding: 20px 100px; background: #f5f5f5; margin: 0; }
            .header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; }
            .nav-wrapper { margin-bottom: 20px; }
            .nav { background: white; padding: 15px 20px; border-radius: 8px; display: inline-flex; gap: 20px; }
            .nav-btn {
                padding: 10px 20px;
                text-decoration: none;
                border-radius: 6px;
                font-weight: bold;
                transition: all 0.3s;
                border: none;
                cursor: pointer;
                font-size: 14px;
                white-space: nowrap;
            }
            .nav-btn.active {
                background: #6b5b47;
                color: white;
            }
            .nav-btn:not(.active) {
                background: #f5f5f5;
                color: #666;
            }
            .nav-btn:not(.active):hover {
                background: #e0e0e0;
            }
            .content { background: white; padding: 30px 40px; border-radius: 8px; }
            .form-group { margin-bottom: 25px; }
            label { display: block; margin-bottom: 8px; font-weight: 600; color: #333; }
            textarea { 
                width: 100%;
                padding: 12px;
                margin: 10px 0;
                border: 1px solid #ddd;
                border-radius: 6px;
                font-family: inherit;
                font-size: 14px;
                line-height: 1.6;
                box-sizing: border-box;
            }
            .save-btn { 
                padding: 12px 32px;
                background: #6b5b47;
                color: white;
                border: none;
                border-radius: 6px;
                cursor: pointer;
                font-size: 16px;
                font-weight: bold;
            }
            .save-btn:hover {
                background: #8b7355;
            }
            .logout-btn { 
                background: #d32f2f;
                padding: 10px 20px;
                color: white;
                text-decoration: none;
                border-radius: 6px;
            }
            .logout-btn:hover {
                background: #b71c1c;
            }
            .success-message {
                background: #e8f5e9;
                color: #2e7d32;
                padding: 12px;
                border-radius: 6px;
                margin-bottom: 20px;
                text-align: center;
            }
        </style>
    </head>
    <body>
        <div class="header">
            <h1>メッセージ管理画面</h1>
            <a href="{{ url_for('logout') }}" class="logout-btn">ログアウト</a>
        </div>
        
        <div class="content" style="margin-bottom: 20px;">
            <h2 style="margin-top: 0; margin-bottom: 15px; font-size: 18px;">📊 システム統計</h2>
            <div style="display: grid; grid-template-columns: repeat(3, 1fr); gap: 15px;">
                <div style="background: #e3f2fd; padding: 20px; border-radius: 8px; text-align: center;">
                    <div style="font-size: 32px; font-weight: bold; color: #1976d2;">{{ customer_count }}</div>
                    <div style="color: #666; margin-top: 5px;">登録顧客数</div>
                </div>
                <div style="background: #fff3e0; padding: 20px; border-radius: 8px; text-align: center;">
                    <div style="font-size: 32px; font-weight: bold; color: #f57c00;">{{ monthly_absences }}</div>
                    <div style="color: #666; margin-top: 5px;">今月の欠勤申請</div>
                </div>
                <div style="background: #fce4ec; padding: 20px; border-radius: 8px; text-align: center;">
                    <div style="font-size: 32px; font-weight: bold; color: #c2185b;">{{ total_absences }}</div>
                    <div style="color: #666; margin-top: 5px;">総欠勤申請数</div>
                </div>
            </div>
        </div>
        
        <div class="nav-wrapper">
            <div class="nav">
                <a href="{{ url_for('admin') }}" class="nav-btn active">メッセージ管理画面</a>
                <a href="{{ url_for('customer_list') }}" class="nav-btn">登録顧客一覧</a>
                <a href="{{ url_for('scrape_page') }}" class="nav-btn">顧客データ取込</a>
                <a href="{{ url_for('absence_list') }}" class="nav-btn">欠勤申請履歴</a>
            </div>
        </div>
        
        <div class="content">
            {% if success %}
            <div class="success-message">✓ メッセージを保存しました（即時反映済み）</div>
            {% endif %}
            
            <form method="POST" action="{{ url_for('update') }}">
                <div class="form-group">
                    <label>代替募集メッセージ（欠勤以外のスタッフへ）:</label>
                    <textarea name="absence_request" rows="5">{{ messages.absence_request }}</textarea>
                </div>
                <div class="form-group">
                    <label>代替確定通知（欠勤以外のスタッフへ）:</label>
                    <textarea name="substitute_confirmed" rows="3">{{ messages.substitute_confirmed }}</textarea>
                </div>
                <div class="form-group">
                    <label>欠勤確認通知（欠勤スタッフ本人へ）:</label>
                    <textarea name="absence_confirmed" rows="4">{{ messages.absence_confirmed }}</textarea>
                </div>
                <button type="submit" class="save-btn">保存</button>
            </form>
        </div>
    </body>
    </html>
    '''
    success = request.args.get('success')
    return render_template_string(template, messages=MESSAGES, success=success, 
                                 customer_count=customer_count, monthly_absences=monthly_absences, 
                                 total_absences=total_absences)

@app.route('/customers')
@admin_required
def customer_list():
    mapping = load_mapping()
    
    # JST変換処理を追加
    JST = timezone(timedelta(hours=9))
    for customer_name, customer_data in mapping.items():
        if isinstance(customer_data, dict) and 'registered_at' in customer_data:
            try:
                utc_time = datetime.fromisoformat(customer_data['registered_at'].replace('Z', '+00:00'))
                jst_time = utc_time.astimezone(JST)
                customer_data['registered_at'] = jst_time.strftime('%Y-%m-%d %H:%M:%S')
            except:
                pass
    
    template = '''
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>顧客一覧</title>
        <style>
            body { font-family: Arial; padding: 20px 100px; background: #f5f5f5; margin: 0; }
            .header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; }
            .nav-wrapper { margin-bottom: 20px; }
            .nav { background: white; padding: 15px 20px; border-radius: 8px; display: inline-flex; gap: 20px; }
            .nav-btn {
                padding: 10px 20px;
                text-decoration: none;
                border-radius: 6px;
                font-weight: bold;
                transition: all 0.3s;
                border: none;
                cursor: pointer;
                font-size: 14px;
                white-space: nowrap;
            }
            .nav-btn.active {
                background: #6b5b47;
                color: white;
            }
            .nav-btn:not(.active) {
                background: #f5f5f5;
                color: #666;
            }
            .nav-btn:not(.active):hover {
                background: #e0e0e0;
            }
            .content { background: white; padding: 30px 40px; border-radius: 8px; }
            table { width: 100%; border-collapse: collapse; }
            th, td { padding: 12px; text-align: left; border-bottom: 1px solid #e0e0e0; }
            th { background: #f5f5f5; font-weight: bold; }
            .logout-btn { 
                background: #d32f2f;
                padding: 10px 20px;
                color: white;
                text-decoration: none;
                border-radius: 6px;
            }
            .logout-btn:hover {
                background: #b71c1c;
            }
        </style>
    </head>
    <body>
        <div class="header">
            <h1>登録顧客一覧</h1>
            <a href="{{ url_for('logout') }}" class="logout-btn">ログアウト</a>
        </div>
        
        <div class="nav-wrapper">
            <div class="nav">
                <a href="{{ url_for('admin') }}" class="nav-btn">メッセージ管理画面</a>
                <a href="{{ url_for('customer_list') }}" class="nav-btn active">登録顧客一覧</a>
                <a href="{{ url_for('scrape_page') }}" class="nav-btn">顧客データ取込</a>
                <a href="{{ url_for('absence_list') }}" class="nav-btn">欠勤申請履歴</a>
            </div>
        </div>
        
        <div class="content">
            <p><strong>合計: {{ mapping|length }}人</strong></p>
            <table>
                <tr>
                    <th>顧客名</th>
                    <th>LINE User ID</th>
                    <th>登録日時</th>
                </tr>
                {% for name, data in mapping.items() %}
                <tr>
                    <td>{{ name }}</td>
                    <td>{{ data.user_id if data.user_id else data }}</td>
                    <td>{{ data.registered_at if data.registered_at else '-' }}</td>
                </tr>
                {% endfor %}
            </table>
        </div>
    </body>
    </html>
    '''
    return render_template_string(template, mapping=mapping)

@app.route('/absences')
@admin_required
def absence_list():
    absences = load_absences()
    grouped_absences = group_absences_by_month(absences)
    current_month = datetime.now().strftime('%Y-%m')
    
    template = '''
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>欠勤申請履歴</title>
        <style>
            body { font-family: Arial; padding: 20px 100px; background: #f5f5f5; margin: 0; }
            .header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; }
            .nav-wrapper { margin-bottom: 20px; }
            .nav { background: white; padding: 15px 20px; border-radius: 8px; display: inline-flex; gap: 20px; }
            .nav-btn {
                padding: 10px 20px;
                text-decoration: none;
                border-radius: 6px;
                font-weight: bold;
                transition: all 0.3s;
                border: none;
                cursor: pointer;
                font-size: 14px;
                white-space: nowrap;
            }
            .nav-btn.active {
                background: #6b5b47;
                color: white;
            }
            .nav-btn:not(.active) {
                background: #f5f5f5;
                color: #666;
            }
            .nav-btn:not(.active):hover {
                background: #e0e0e0;
            }
            .content { background: white; padding: 30px 40px; border-radius: 8px; }
            .month-section { margin-bottom: 30px; }
            .month-header {
                background: #f5f5f5;
                padding: 12px 20px;
                border-radius: 6px;
                display: flex;
                justify-content: space-between;
                align-items: center;
                cursor: pointer;
                margin-bottom: 10px;
            }
            .month-header:hover {
                background: #e8e8e8;
            }
            .month-title { font-weight: 600; font-size: 16px; }
            .month-count { color: #666; font-size: 14px; }
            .month-content { display: none; }
            .month-content.active { display: block; }
            .toggle-icon { transition: transform 0.3s; }
            .toggle-icon.rotated { transform: rotate(180deg); }
            table { width: 100%; border-collapse: collapse; }
            th, td { padding: 12px; text-align: left; border-bottom: 1px solid #e0e0e0; }
            th { background: #f5f5f5; font-weight: bold; }
            .reason-badge { 
                background: #ffebee; 
                color: #d32f2f; 
                padding: 4px 8px; 
                border-radius: 4px; 
                font-size: 12px;
                font-weight: 500;
            }
            .logout-btn { 
                background: #d32f2f;
                padding: 10px 20px;
                color: white;
                text-decoration: none;
                border-radius: 6px;
            }
            .logout-btn:hover {
                background: #b71c1c;
            }
        </style>
    </head>
    <body>
        <div class="header">
    <h1>欠勤申請履歴</h1>
    <div style="display: flex; align-items: center; gap: 15px;">
        <a href="{{ url_for('export_absences') }}" style="background: #4caf50; color: white; padding: 10px 20px; text-decoration: none; border-radius: 6px; font-size: 14px; font-weight: bold;">CSV出力</a>
        <a href="{{ url_for('logout') }}" class="logout-btn">ログアウト</a>
    </div>
</div>
        
        <div class="nav-wrapper">
            <div class="nav">
                <a href="{{ url_for('admin') }}" class="nav-btn">メッセージ管理画面</a>
                <a href="{{ url_for('customer_list') }}" class="nav-btn">登録顧客一覧</a>
                <a href="{{ url_for('scrape_page') }}" class="nav-btn">顧客データ取込</a>
                <a href="{{ url_for('absence_list') }}" class="nav-btn active">欠勤申請履歴</a>
            </div>
        </div>
        
        <div class="content">
            <p><strong>合計: {{ absences|length }}件</strong></p>
            
            {% if grouped_absences %}
                {% for month, month_absences in grouped_absences.items() %}
                <div class="month-section">
                    <div class="month-header" onclick="toggleMonth('{{ month }}')">
                        <div>
                            <span class="month-title">{{ month[:4] }}年{{ month[5:7]|int }}月</span>
                            <span class="month-count">（{{ month_absences|length }}件）</span>
                        </div>
                        <span class="toggle-icon" id="icon-{{ month }}">▼</span>
                    </div>
                    <div class="month-content {% if month == current_month %}active{% endif %}" id="content-{{ month }}">
                        <table>
                            <tr>
                                <th>スタッフ名</th>
                                <th>欠勤理由</th>
                                <th>状況説明</th>
                                <th>代替可能日時</th>
                                <th>申請日時</th>
                                <th>操作</th>
                            </tr>
                            {% for absence in month_absences|reverse %}
                            <tr>
                                <td>{{ get_full_name(absence.staff_name) }}</td>
                                <td><span class="reason-badge">{{ absence.reason }}</span></td>
                                <td>{{ absence.details }}</td>
                                <td>{{ absence.alternative_date if absence.alternative_date else '-' }}</td>
                                <td>{{ absence.submitted_at[:10] }} {{ absence.submitted_at[11:16] }}</td>
                                <td>
                                    {% if absence.status == 'pending' %}
                                    <form method="POST" action="/admin/approve_absence" style="margin: 0;">
                                        <input type="hidden" name="absence_id" value="{{ absence.id }}">
                                        <button type="submit" style="padding: 6px 12px; background: #4caf50; color: white; border: none; border-radius: 4px; cursor: pointer; font-size: 12px;">承認</button>
                                    </form>
                                    {% else %}
                                    <span style="color: #4caf50; font-size: 12px;">✓ 承認済</span>
                                    {% endif %}
                                </td>
                            </tr>
                            {% endfor %}
                        </table>
                    </div>
                </div>
                {% endfor %}
            {% else %}
                <p style="color: #999; text-align: center; padding: 40px 0;">欠勤申請はまだありません</p>
            {% endif %}
        </div>
        
        <script>
            function toggleMonth(month) {
                const content = document.getElementById('content-' + month);
                const icon = document.getElementById('icon-' + month);
                content.classList.toggle('active');
                icon.classList.toggle('rotated');
            }
            
            window.onload = function() {
                const currentMonth = '{{ current_month }}';
                const currentIcon = document.getElementById('icon-' + currentMonth);
                if (currentIcon) {
                    currentIcon.classList.add('rotated');
                }
            };
        </script>
    </body>
    </html>
    '''
    return render_template_string(template, absences=absences, grouped_absences=grouped_absences, 
                                   current_month=current_month, get_full_name=get_full_name)

@app.route('/update', methods=['POST'])
@admin_required
def update():
    absence_msg = request.form.get('absence_request')
    substitute_msg = request.form.get('substitute_confirmed')
    absence_conf_msg = request.form.get('absence_confirmed')
    
    # JSONファイルとして保存（改行もそのまま保存される）
    messages = {
        "absence_request": absence_msg,
        "substitute_confirmed": substitute_msg,
        "absence_confirmed": absence_conf_msg
    }
    save_messages(messages)
    
    return redirect(url_for('admin', success='1'))

@app.route('/webhook/line', methods=['POST'])
def webhook():
    print(f"[WEBHOOK] リクエスト受信: {request.json}")
    try:
        # メッセージを動的に読み込む
        MESSAGES = load_messages()
        
        events = request.json.get('events', [])
        for event in events:
            if event['type'] == 'message':
                user_id = event['source']['userId']
                text = event['message']['text']
                staff_info = staff_mapping.get(user_id)
                
                if staff_info:
                    staff_name = staff_info['name']
                    
                    if "欠勤" in text or "休み" in text:
                        for uid, info in staff_mapping.items():
                            if uid != user_id:
                                msg = MESSAGES["absence_request"].format(staff_name=staff_name)
                                send_line_message(uid, msg)
                    
                    elif "出勤" in text or "できます" in text:
                        for uid, info in staff_mapping.items():
                            if uid != user_id:
                                notification = MESSAGES["substitute_confirmed"].format(substitute_name=staff_name)
                                send_line_message(uid, notification)
                
                else:
                    mapping = load_mapping()
                    existing = None
                    for name, data in mapping.items():
                        stored_id = data['user_id'] if isinstance(data, dict) else data
                        if stored_id == user_id:
                            existing = name
                            break
                    
                    # 新規でも既存でも名前更新を試みる
                    if len(text) >= 2:
                        cleaned_name = clean_customer_name(text)
                        if cleaned_name and len(cleaned_name) >= 2:
                            result = save_mapping(cleaned_name, user_id)
                        
        return 'OK', 200
    except Exception as e:
        print(f"[WEBHOOK] エラー: {e}")
        import traceback
        traceback.print_exc()
        return 'Error', 500

@app.route("/api/scrape-hotpepper", methods=["POST"])
@admin_required
def scrape_hotpepper():
    """ホットペッパーから顧客情報をスクレイピング"""
    try:
        data = request.json
        url = data.get("url")
        
        if not url:
            return jsonify({"success": False, "error": "URLが必要です"}), 400
        
        # 実際のページを取得
        response = requests.get(url, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
        soup = BeautifulSoup(response.text, 'html.parser')
        
        customers = []
        new_count = 0
        
        # ホットペッパーの予約情報を抽出
        for elem in soup.find_all(['span', 'div', 'td'], class_=['customer', 'name', 'reservation']):
            name = elem.get_text().strip()
            if name and len(name) >= 2 and len(name) <= 20:
                mapping = load_mapping()
                if name not in mapping:
                    temp_id = f"pending_{datetime.now().timestamp()}"
                    save_mapping(name, temp_id)
                    customers.append({"name": name, "status": "新規登録"})
                    new_count += 1
                else:
                    customers.append({"name": name, "status": "登録済み"})
        
        return jsonify({
            "success": True, 
            "customers": customers, 
            "count": len(customers),
            "new_count": new_count,
            "message": f"合計{len(customers)}件（新規{new_count}件）を取得しました"
        })
        
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/admin/scrape")
@admin_required
def scrape_page():
    """スクレイピング管理画面"""
    SCRAPE_TEMPLATE = """<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>顧客データ取込</title>
    <style>
        body { font-family: Arial; padding: 20px 100px; background: #f5f5f5; margin: 0; }
        .header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; }
        .nav-wrapper { margin-bottom: 20px; }
        .nav { background: white; padding: 15px 20px; border-radius: 8px; display: inline-flex; gap: 20px; }
        .nav-btn {
            padding: 10px 20px;
            text-decoration: none;
            border-radius: 6px;
            font-weight: bold;
            transition: all 0.3s;
            border: none;
            cursor: pointer;
            font-size: 14px;
            white-space: nowrap;
        }
        .nav-btn.active {
            background: #6b5b47;
            color: white;
        }
        .nav-btn:not(.active) {
            background: #f5f5f5;
            color: #666;
        }
        .nav-btn:not(.active):hover {
            background: #e0e0e0;
        }
        .content { background: white; padding: 30px 40px; border-radius: 8px; }
        .logout-btn { 
            background: #d32f2f;
            padding: 10px 20px;
            color: white;
            text-decoration: none;
            border-radius: 6px;
        }
        .logout-btn:hover {
            background: #b71c1c;
        }
        input { width: 100%; padding: 12px; margin: 15px 0; border: 1px solid #ddd; border-radius: 4px; box-sizing: border-box; }
        button { background: #6b5b47; color: white; padding: 10px 20px; border: none; border-radius: 5px; cursor: pointer; font-size: 14px; }
        button:hover { background: #5a4a37; }
        #result { margin-top: 20px; padding: 15px; border-radius: 4px; }
        #result h3 { margin: 0 0 10px 0; }
    </style>
</head>
<body>
    <div class="header">
        <h1>ホットペッパー顧客データ取込</h1>
        <a href="{{ url_for('logout') }}" class="logout-btn">ログアウト</a>
    </div>
    
    <div class="nav-wrapper">
        <div class="nav">
            <a href="{{ url_for('admin') }}" class="nav-btn">メッセージ管理画面</a>
            <a href="{{ url_for('customer_list') }}" class="nav-btn">登録顧客一覧</a>
            <a href="{{ url_for('scrape_page') }}" class="nav-btn active">顧客データ取込</a>
            <a href="{{ url_for('absence_list') }}" class="nav-btn">欠勤申請履歴</a>
        </div>
    </div>
    
    <div class="content">
        <form onsubmit="scrapeData(event)">
            <label style="font-weight: bold; display: block; margin-bottom: 5px;">ホットペッパーURL:</label>
            <input type="url" id="url" placeholder="https://..." required>
            <button type="submit">データ取得</button>
        </form>
        <div id="result"></div>
    </div>
    
    <script>
    async function scrapeData(e) {
        e.preventDefault();
        const url = document.getElementById("url").value;
        const result = document.getElementById("result");
        result.innerHTML = "<p>取得中...</p>";
        result.style.background = "#e3f2fd";
        result.style.border = "1px solid #2196f3";
        try {
            const response = await fetch("/api/scrape-hotpepper", {
                method: "POST",
                headers: {"Content-Type": "application/json"},
                body: JSON.stringify({url})
            });
            const data = await response.json();
            if (data.success) {
    result.style.background = "#e8f5e9";
    result.style.border = "1px solid #4caf50";
    let html = '<h3>✅ 成功！</h3>';
    html += '<p>' + data.message + '</p>';
    if (data.customers && data.customers.length > 0) {
        html += '<ul>';
        data.customers.forEach(c => {
            html += '<li>' + c.name + ' (' + c.status + ')</li>';
        });
        html += '</ul>';
    }
    result.innerHTML = html;
}
                result.style.background = "#ffebee";
                result.style.border = "1px solid #f44336";
                result.innerHTML = '<h3>❌ エラー</h3><p>' + data.error + '</p>';
            }
        } catch (err) {
            result.style.background = "#ffebee";
            result.style.border = "1px solid #f44336";
            result.innerHTML = '<h3>❌ エラー</h3><p>' + err.message + '</p>';
        }
    }
    </script>
</body>
</html>"""
    return render_template_string(SCRAPE_TEMPLATE)

@app.route('/export/absences')
@admin_required
def export_absences():
    """欠勤履歴をCSVでエクスポート"""
    absences = load_absences()
    si = StringIO()
    writer = csv.writer(si)
    writer.writerow(['スタッフ名', '欠勤理由', '状況説明', '代替可能日時', '申請日時'])
    for absence in absences:
        writer.writerow([
            absence.get('staff_name', ''),
            absence.get('reason', ''),
            absence.get('details', ''),
            absence.get('alternative_date', ''),
            absence.get('submitted_at', '')[:19].replace('T', ' ')
        ])
    output = si.getvalue()
    si.close()
    response = make_response(output)
    response.headers['Content-Type'] = 'text/csv; charset=utf-8-sig'
    response.headers['Content-Disposition'] = f'attachment; filename=absences_{datetime.now().strftime("%Y%m%d")}.csv'
    return response

# LINE Webhook - 自動顧客登録（修正版）
@app.route('/webhook', methods=['POST'])
def line_webhook():
    try:
        body = request.get_json()
        events = body.get('events', [])
        
        for event in events:
            if event['type'] == 'message':
                user_id = event['source']['userId']
                message_text = event.get('message', {}).get('text', '')
                
                # 既存ユーザーは処理しない（名前上書き防止）
                check_headers = {"apikey": SUPABASE_KEY}
                check_res = requests.get(f"{SUPABASE_URL}/rest/v1/customers?line_user_id=eq.{user_id}", headers=check_headers)
                if check_res.status_code == 200 and len(check_res.json()) > 0:
                    print(f"既存ユーザー: {user_id} → スキップ")
                    continue
                
                # メッセージ本文が名前っぽい場合は名前として処理
                if message_text and 2 <= len(message_text) <= 20 and not any(c in message_text for c in ['http', '予約', '確認', 'キャンセル']):
                    # メッセージを名前として登録/更新
                    if save_mapping(message_text, user_id):
                        print(f"✅ 顧客名更新: {message_text} ({user_id})")
                else:
                    # プロフィール取得で新規登録
                    headers = {'Authorization': f'Bearer {LINE_BOT_TOKEN}'}
                    profile_url = f'https://api.line.me/v2/bot/profile/{user_id}'
                    profile_response = requests.get(profile_url, headers=headers)
                    
                    if profile_response.status_code == 200:
                        profile = profile_response.json()
                        display_name = profile.get('displayName', 'Unknown')
                        
                        mapping = load_mapping()
                        if display_name not in mapping:
                            if save_mapping(display_name, user_id):
                                print(f"✅ 新規顧客登録: {display_name} ({user_id})")
        
        return jsonify({'status': 'ok'}), 200
    except Exception as e:
        print(f"❌ Webhook エラー: {str(e)}")
        return jsonify({'status': 'error'}), 500

# LINE Webhook - スタッフ用
@app.route('/webhook/staff', methods=['POST'])
def line_webhook_staff():
    try:
        body = request.get_json()
        events = body.get('events', [])
        
        for event in events:
            if event['type'] == 'message':
                user_id = event['source']['userId']
                
                # プロフィール取得（スタッフ用トークン使用）
                headers = {'Authorization': f'Bearer {LINE_BOT_TOKEN_STAFF}'}
                profile_url = f'https://api.line.me/v2/bot/profile/{user_id}'
                profile_response = requests.get(profile_url, headers=headers)
                
                if profile_response.status_code == 200:
                    profile = profile_response.json()
                    display_name = profile.get('displayName', 'Unknown')
                    
                    # 自動登録
                    mapping = load_mapping()
                    if display_name not in mapping:
                        if save_mapping(display_name, user_id):
                            print(f"✅ 新規スタッフ登録: {display_name} ({user_id})")
                        else:
                            print(f"❌ スタッフ登録失敗: {display_name} ({user_id})")
                    else:
                        print(f"[情報] 既に登録済み（スタッフ）: {display_name} ({user_id})")
                else:
                    print(f"❌ プロフィール取得失敗（スタッフ）: status_code={profile_response.status_code}, user_id={user_id}")
        
        return jsonify({'status': 'ok'}), 200
    except Exception as e:
        print(f"❌ Webhook エラー（スタッフ）: {str(e)}")
        return jsonify({'status': 'error'}), 500


@app.route('/admin/test_http_detailed')
@login_required
@admin_required
def test_http_detailed():
    import requests
    import time
    
    results = []
    
    # ========================================
    # Test 1: 基本的なHTTPリクエスト（タイムアウト60秒）
    # ========================================
    results.append("<h2>Test 1: 基本HTTPリクエスト（タイムアウト60秒）</h2>")
    try:
        start = time.time()
        response = requests.get(
            'https://salonboard.com/login/',
            timeout=180,  # ← 120秒から60秒に変更
            allow_redirects=True
        )
        elapsed = time.time() - start
        results.append(f"✅ <strong>成功</strong>")
        results.append(f"   ステータスコード: {response.status_code}")
        results.append(f"   所要時間: {elapsed:.3f}秒")
        results.append(f"   レスポンスサイズ: {len(response.content)} bytes")
    except requests.exceptions.Timeout:
        elapsed = time.time() - start
        results.append(f"❌ <strong>失敗</strong>: タイムアウト（60秒）")
        results.append(f"   実際の経過時間: {elapsed:.3f}秒")
    except Exception as e:
        results.append(f"❌ <strong>失敗</strong>: {str(e)}")
    
    # ========================================
    # Test 2: User-Agent追加
    # ========================================
    results.append("<h2>Test 2: User-Agent追加</h2>")
    try:
        start = time.time()
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        }
        response = requests.get(
            'https://salonboard.com/login/',
            headers=headers,
            timeout=180,  # ← 120秒から60秒に変更
            allow_redirects=True
        )
        elapsed = time.time() - start
        results.append(f"✅ <strong>成功</strong>")
        results.append(f"   ステータスコード: {response.status_code}")
        results.append(f"   所要時間: {elapsed:.3f}秒")
        results.append(f"   レスポンスサイズ: {len(response.content)} bytes")
        results.append(f"   最終URL: {response.url}")
    except requests.exceptions.Timeout:
        elapsed = time.time() - start
        results.append(f"❌ <strong>失敗</strong>: タイムアウト（60秒）")
        results.append(f"   実際の経過時間: {elapsed:.3f}秒")
    except Exception as e:
        results.append(f"❌ <strong>失敗</strong>: {str(e)}")
    
    # ========================================
    # Test 3: ブラウザに近いヘッダー
    # ========================================
    results.append("<h2>Test 3: 完全なブラウザヘッダー</h2>")
    try:
        start = time.time()
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'ja,en-US;q=0.9,en;q=0.8',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1'
        }
        response = requests.get(
            'https://salonboard.com/login/',
            headers=headers,
            timeout=180,  # ← 120秒から60秒に変更
            allow_redirects=True
        )
        elapsed = time.time() - start
        results.append(f"✅ <strong>成功</strong>")
        results.append(f"   ステータスコード: {response.status_code}")
        results.append(f"   所要時間: {elapsed:.3f}秒")
        results.append(f"   レスポンスサイズ: {len(response.content)} bytes")
        results.append(f"   Content-Type: {response.headers.get('Content-Type', 'N/A')}")
        results.append(f"   Server: {response.headers.get('Server', 'N/A')}")
    except requests.exceptions.Timeout:
        elapsed = time.time() - start
        results.append(f"❌ <strong>失敗</strong>: タイムアウト（60秒）")
        results.append(f"   実際の経過時間: {elapsed:.3f}秒")
    except Exception as e:
        results.append(f"❌ <strong>失敗</strong>: {str(e)}")
    
    # ========================================
    # Test 4: セッション使用（Cookie保持）
    # ========================================
    results.append("<h2>Test 4: セッション使用</h2>")
    try:
        start = time.time()
        session = requests.Session()
        session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        })
        response = session.get(
            'https://salonboard.com/login/',
            timeout=180,  # ← 120秒から60秒に変更
            allow_redirects=True
        )
        elapsed = time.time() - start
        results.append(f"✅ <strong>成功</strong>")
        results.append(f"   ステータスコード: {response.status_code}")
        results.append(f"   所要時間: {elapsed:.3f}秒")
        results.append(f"   Cookie数: {len(response.cookies)}")
        results.append(f"   リダイレクト回数: {len(response.history)}")
    except requests.exceptions.Timeout:
        elapsed = time.time() - start
        results.append(f"❌ <strong>失敗</strong>: タイムアウト（60秒）")
        results.append(f"   実際の経過時間: {elapsed:.3f}秒")
    except Exception as e:
        results.append(f"❌ <strong>失敗</strong>: {str(e)}")
    
    # ========================================
    # 結論
    # ========================================
    results.append("<hr>")
    results.append("<h2>📊 診断結果</h2>")
    results.append("<p>どのテストが成功したかで、問題の原因を特定できます</p>")
    results.append("<ul>")
    results.append("<li>すべて失敗 → SALON BOARDサーバー側の問題</li>")
    results.append("<li>User-Agent追加で成功 → Bot検出の可能性</li>")
    results.append("<li>完全ヘッダーで成功 → ヘッダー不足</li>")
    results.append("<li>セッション使用で成功 → Cookie/セッション管理の問題</li>")
    results.append("</ul>")
    
    return f"""
    <html>
    <head>
        <meta charset="UTF-8">
        <title>HTTP詳細診断テスト</title>
        <style>
            body {{
                font-family: Arial, sans-serif;
                padding: 20px;
                max-width: 900px;
                margin: 0 auto;
                background-color: #f5f5f5;
            }}
            h1 {{
                color: #333;
                border-bottom: 3px solid #007bff;
                padding-bottom: 10px;
            }}
            h2 {{
                color: #007bff;
                margin-top: 30px;
                border-left: 5px solid #007bff;
                padding-left: 10px;
            }}
            .result {{
                background-color: white;
                padding: 20px;
                border-radius: 8px;
                box-shadow: 0 2px 4px rgba(0,0,0,0.1);
                margin-bottom: 20px;
            }}
            a {{
                display: inline-block;
                margin-top: 20px;
                padding: 10px 20px;
                background-color: #007bff;
                color: white;
                text-decoration: none;
                border-radius: 5px;
            }}
            a:hover {{
                background-color: #0056b3;
            }}
        </style>
    </head>
    <body>
        <h1>HTTP詳細診断テスト</h1>
        <p>様々な方法でHTTPリクエストを試します（各テスト最大60秒）</p>
        <div class="result">
            {''.join(results)}
        </div>
        <a href="/admin">← 管理画面に戻る</a>
    </body>
    </html>
    """


@app.route('/test_salonboard_login', methods=['GET'])
def test_salonboard_login():
    """SALONBOARD ログインテスト（Firefox使用）"""
    from playwright.sync_api import sync_playwright
    import re
    
    try:
        login_id = os.getenv('SALONBOARD_LOGIN_ID')
        password = os.getenv('SALONBOARD_LOGIN_PASSWORD')
        
        if not login_id or not password:
            return jsonify({
                'success': False,
                'error': '環境変数が設定されていません'
            }), 500
        
        with sync_playwright() as p:
            browser = p.firefox.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
            page = browser.new_page()
            page.set_default_timeout(30000)
            
            page.goto('https://salonboard.com/login/')
            page.wait_for_selector('input[name="userId"]', timeout=20000)
            page.fill('input[name="userId"]', login_id)
            page.fill('input[name="password"]', password)
            page.press('input[name="password"]', 'Enter')
            page.wait_for_url('**/KLP/**', timeout=20000)
            
            final_url = page.url
            success = '/KLP/' in final_url
            
            browser.close()
            
            return jsonify({
                'success': success,
                'message': 'ログイン成功' if success else 'ログイン失敗',
                'final_url': final_url,
                'browser': 'firefox',
                'timestamp': datetime.now().isoformat()
            })
            
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e),
            'error_type': type(e).__name__,
            'timestamp': datetime.now().isoformat()
        }), 500


# グローバル変数
login_results = {}
login_lock = threading.Lock()

@app.route('/health_check', methods=['GET'])
def health_check():
    """環境確認用"""
    import sys
    return jsonify({
        'status': 'ok',
        'python_version': sys.version,
        'salonboard_id_set': bool(os.getenv('SALONBOARD_LOGIN_ID')),
        'salonboard_pwd_set': bool(os.getenv('SALONBOARD_LOGIN_PASSWORD')),
        'timestamp': datetime.now().isoformat()
    })

@app.route('/test_async', methods=['GET'])
def test_async():
    """subprocess版非同期ログインテスト"""
    import subprocess
    task_id = datetime.now().strftime('%Y%m%d%H%M%S%f')
    
    def bg_login():
        try:
            print(f"[SUBPROCESS] タスク開始: {task_id}", flush=True)
            
            # 完全に独立したプロセスとして実行（180秒タイムアウト）
            result = subprocess.run(
                ['python3', 'salonboard_login.py', task_id],
                capture_output=True,
                text=True,
                timeout=180,
                env=os.environ.copy()
            )
            
            print(f"[SUBPROCESS] stdout: {result.stdout}", flush=True)
            print(f"[SUBPROCESS] stderr: {result.stderr}", flush=True)
            
            # 結果ファイルから読み込み
            result_file = f"/tmp/login_result_{task_id}.json"
            if os.path.exists(result_file):
                with open(result_file, 'r') as f:
                    result_data = json.load(f)
                with login_lock:
                    login_results[task_id] = result_data
                os.remove(result_file)
            else:
                with login_lock:
                    login_results[task_id] = {
                        'success': False,
                        'error': 'Result file not found',
                        'stdout': result.stdout,
                        'stderr': result.stderr
                    }
                    
        except subprocess.TimeoutExpired:
            print(f"[SUBPROCESS] タイムアウト（180秒）: {task_id}", flush=True)
            with login_lock:
                login_results[task_id] = {
                    'success': False,
                    'error': 'Subprocess timeout after 180 seconds',
                    'error_type': 'TimeoutExpired'
                }
        except Exception as e:
            print(f"[SUBPROCESS] エラー: {str(e)}", flush=True)
            with login_lock:
                login_results[task_id] = {
                    'success': False,
                    'error': str(e),
                    'error_type': type(e).__name__
                }
    
    threading.Thread(target=bg_login, daemon=True).start()
    return jsonify({
        'status': 'processing',
        'task_id': task_id,
        'check_url': f'/result/{task_id}',
        'message': 'subprocess版ログイン処理を開始しました（タイムアウト180秒）'
    }), 202

@app.route('/result/<task_id>', methods=['GET'])
def get_result(task_id):
    """結果確認"""
    with login_lock:
        return jsonify(login_results.get(task_id, {'status': 'processing'}))

if __name__ == '__main__':
    # 初期ファイル作成
    if not os.path.exists(MAPPING_FILE):
        with open(MAPPING_FILE, 'w') as f:
            json.dump({}, f)
    
    if not os.path.exists(ABSENCE_FILE):
        with open(ABSENCE_FILE, 'w') as f:
            json.dump([], f)
    
    if not os.path.exists(MESSAGES_FILE):
        default_messages = {
            "absence_request": "{staff_name}が本日欠勤となりました。\n代替出勤が可能でしたら「出勤できます」とメッセージしてください。\n\nよろしくお願いします。",
            "substitute_confirmed": "{substitute_name}が出勤してくれることになりました。\n連絡が入りました。",
            "absence_confirmed": "欠勤申請を受け付けました。\n\n理由: {reason}\n詳細: {details}\n\nご連絡ありがとうございます。\n代替スタッフへの連絡を行いました。無理せずお過ごしください。"
        }
        save_messages(default_messages)
    
    # 24時間ごとにバックアップ
    schedule.every(24).hours.do(backup_customers)
    
    # スケジューラーを別スレッドで開始
    threading.Thread(target=run_scheduler, daemon=True).start()
    
    # 起動時に1回実行
    backup_customers()
    
    print("="*50)
    print("✅ 認証機能付きシステム起動（即時反映対応）")
    print("="*50)
    print("ログインページ: http://localhost:5001/")
    print("\n管理者アカウント:")
    print("  ID: admin / パスワード: admin123")
    print("\nスタッフアカウント:")
    print("  ID: kambara / パスワード: kambara123")
    print("  ID: saori / パスワード: saori123")
    print("="*50)
    
    # Renderの環境変数PORTを使用（ローカルは5001）
    port = int(os.environ.get('PORT', 5001))
    app.run(debug=False, host='0.0.0.0', port=port)

@app.route('/debug/check_files', methods=['GET'])

@app.route('/debug/check_files', methods=['GET'])
def debug_check_files():
    """Dockerコンテナ内のファイル確認"""
    import subprocess
    import os
    
    checks = {}
    
    # 1. カレントディレクトリ
    checks['current_dir'] = os.getcwd()
    
    # 2. salonboard_login.py存在確認
    checks['salonboard_login_exists'] = os.path.exists('salonboard_login.py')
    checks['salonboard_login_path'] = os.path.abspath('salonboard_login.py') if checks['salonboard_login_exists'] else None
    
    # 3. 実行権限確認
    if checks['salonboard_login_exists']:
        checks['salonboard_login_executable'] = os.access('salonboard_login.py', os.X_OK)
        checks['salonboard_login_size'] = os.path.getsize('salonboard_login.py')
    
    # 4. /app ディレクトリ内容
    try:
        checks['app_dir_contents'] = subprocess.run(['ls', '-la', '/app'], capture_output=True, text=True, timeout=5).stdout
    except:
        checks['app_dir_contents'] = 'ERROR'
    
    # 5. Python実行確認
    try:
        checks['python3_version'] = subprocess.run(['python3', '--version'], capture_output=True, text=True, timeout=5).stdout
    except:
        checks['python3_version'] = 'ERROR'
    
    # 6. /tmpへの書き込み確認
    try:
        test_file = '/tmp/test_write.txt'
        with open(test_file, 'w') as f:
            f.write('test')
        checks['tmp_writable'] = os.path.exists(test_file)
        os.remove(test_file)
    except:
        checks['tmp_writable'] = False
    
    # 7. 環境変数確認
    checks['env_salonboard_id'] = bool(os.getenv('SALONBOARD_LOGIN_ID'))
    checks['env_salonboard_pwd'] = bool(os.getenv('SALONBOARD_LOGIN_PASSWORD'))
    
    # 8. メモリ情報
    try:
        checks['memory_info'] = subprocess.run(['free', '-h'], capture_output=True, text=True, timeout=5).stdout
    except:
        checks['memory_info'] = 'ERROR'
    
    # 9. Playwrightブラウザ確認
    try:
        checks['playwright_browsers'] = subprocess.run(['ls', '-la', '/ms-playwright'], capture_output=True, text=True, timeout=5).stdout
    except:
        checks['playwright_browsers'] = 'ERROR'
    
    # 10. salonboard_login.pyの内容（最初の50行）
    if checks['salonboard_login_exists']:
        try:
            with open('salonboard_login.py', 'r') as f:
                checks['salonboard_login_content'] = ''.join(f.readlines()[:50])
        except:
            checks['salonboard_login_content'] = 'ERROR'
    
    return jsonify(checks), 200


@app.route('/debug/test_subprocess', methods=['GET'])
def debug_test_subprocess():
    """subprocessテスト"""
    import subprocess
    
    results = {}
    
    # 1. 単純なコマンド
    try:
        result = subprocess.run(['echo', 'test'], capture_output=True, text=True, timeout=5)
        results['echo_test'] = {'stdout': result.stdout, 'stderr': result.stderr, 'returncode': result.returncode}
    except Exception as e:
        results['echo_test'] = {'error': str(e)}
    
    # 2. python3テスト
    try:
        result = subprocess.run(['python3', '-c', 'print("hello")'], capture_output=True, text=True, timeout=5)
        results['python3_test'] = {'stdout': result.stdout, 'stderr': result.stderr, 'returncode': result.returncode}
    except Exception as e:
        results['python3_test'] = {'error': str(e)}
    
    # 3. salonboard_login.py実行テスト（短時間）
    try:
        result = subprocess.run(
            ['python3', 'salonboard_login.py', 'test_debug'],
            capture_output=True,
            text=True,
            timeout=10,
            env=os.environ.copy()
        )
        results['salonboard_login_test'] = {
            'stdout': result.stdout[:1000],
            'stderr': result.stderr[:1000],
            'returncode': result.returncode
        }
    except subprocess.TimeoutExpired:
        results['salonboard_login_test'] = {'error': 'Timeout after 10 seconds'}
    except Exception as e:
        results['salonboard_login_test'] = {'error': str(e), 'type': type(e).__name__}
    
    return jsonify(results), 200


@app.route('/debug/test_playwright_import', methods=['GET'])
def debug_test_playwright_import():
    """Playwrightインポートテスト"""
    import subprocess
    
    try:
        result = subprocess.run(
            ['python3', 'test_playwright_import.py'],
            capture_output=True,
            text=True,
            timeout=300,
            env=os.environ.copy()
        )
        
        return jsonify({
            'success': True,
            'stdout': result.stdout,
            'stderr': result.stderr,
            'returncode': result.returncode
        }), 200
        
    except subprocess.TimeoutExpired as e:
        return jsonify({
            'success': False,
            'error': 'Timeout after 60 seconds',
            'stdout': e.stdout.decode() if e.stdout else '',
            'stderr': e.stderr.decode() if e.stderr else ''
        }), 200
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e),
            'error_type': type(e).__name__
        }), 500


@app.route('/debug/test_salonboard_direct', methods=['GET'])
def debug_test_salonboard_direct():
    """salonboard_login.pyを直接実行"""
    import subprocess
    
    try:
        result = subprocess.run(
            ['python3', 'salonboard_login.py', 'test_render_debug'],
            capture_output=True,
            text=True,
            timeout=300,
            env=os.environ.copy()
        )
        
        return jsonify({
            'success': True,
            'stdout': result.stdout,
            'stderr': result.stderr,
            'returncode': result.returncode
        }), 200
        
    except subprocess.TimeoutExpired as e:
        return jsonify({
            'success': False,
            'error': 'Timeout after 60 seconds',
            'stdout': e.stdout.decode() if e.stdout else '',
            'stderr': e.stderr.decode() if e.stderr else ''
        }), 200
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e),
            'error_type': type(e).__name__
        }), 500

@app.route('/api/scrape_today', methods=['GET', 'POST'])
def api_scrape_today():
    """当日予約から電話番号を取得してcustomersに追加"""
    try:
        import subprocess
        result = subprocess.run(
            ['python3', 'scrape_today.py'],
            capture_output=True,
            text=True,
            timeout=300
        )
        return jsonify({
            'success': result.returncode == 0,
            'stdout': result.stdout,
            'stderr': result.stderr
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500
    
@app.route('/api/scrape_daily_test', methods=['GET', 'POST'])
def scrape_daily_test():
    """テスト用：スクレイピングのみ、LINE送信なし"""
    try:
        import subprocess
        
        result = subprocess.run(
            ['python3', 'scrape_and_upload.py'],
            capture_output=True,
            text=True,
            timeout=300
        )
        
        return jsonify({
            "success": True,
            "scrape_stdout": result.stdout,
            "scrape_stderr": result.stderr,
            "scrape_returncode": result.returncode,
            "note": "テストモード：LINE送信はスキップされました"
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/scrape_daily_DISABLED', methods=['GET'])
def scrape_daily():
    """毎日のスクレイピング実行 + リマインド送信"""
    try:
        import subprocess
        
        # 1. スクレイピング実行
        result = subprocess.run(
            ['python3', 'scrape_and_upload.py'],
            capture_output=True,
            text=True,
            timeout=300
        )
        scrape_output = result.stdout
        
        # 2. リマインド送信（テストモード：神原のみ）
        reminder_results = send_reminder_notifications(test_mode=True)
        
        return jsonify({
            "success": True,
            "scrape_stdout": scrape_output,
            "scrape_stderr": result.stderr,
            "scrape_returncode": result.returncode,
            "reminder_results": reminder_results
        })
    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


def send_reminder_notifications(test_mode=False):
    """3日後・7日後の予約にリマインド通知を送信"""
    import re
    from datetime import datetime, timedelta, timezone
    
    JST = timezone(timedelta(hours=9))
    today = datetime.now(JST)
    results = {"3days": {"sent": 0, "failed": 0, "no_match": 0}, "7days": {"sent": 0, "failed": 0, "no_match": 0}}
    
    # テストモード: 神原のみに送信
    KAMBARA_PHONE = "09015992055"
    
    headers = {
        'apikey': SUPABASE_KEY,
        'Authorization': f'Bearer {SUPABASE_KEY}',
        'Content-Type': 'application/json'
    }
    
    # 顧客データを取得
    cust_response = requests.get(f'{SUPABASE_URL}/rest/v1/customers?select=*', headers=headers)
    if cust_response.status_code != 200:
        return {"error": "顧客データ取得失敗"}
    customers = cust_response.json()
    
    # 電話番号→顧客、名前→顧客マッピング
    phone_to_customer = {c['phone']: c for c in customers if c.get('phone')}
    name_to_customer = {}
    for c in customers:
        if c.get('name'):
            normalized = c['name'].replace(" ", "").replace("　", "").replace("★", "").strip()
            name_to_customer[normalized] = c
    
    for days, label in [(3, "3days"), (7, "7days")]:
        target_date = (today + timedelta(days=days))
        target_date_str = target_date.strftime("%Y-%m-%d")
        scrape_date_str = today.strftime("%Y-%m-%d")
        
        # 8weeks_bookingsからD-3/D-7の予約を取得
        book_response = requests.get(
            f'{SUPABASE_URL}/rest/v1/8weeks_bookings?visit_datetime=gte.{target_date_str}T00:00:00&visit_datetime=lt.{target_date_str}T23:59:59&select=*',
            headers=headers
        )
        if book_response.status_code != 200:
            continue
        
        bookings = book_response.json()        
        for booking in bookings:
            customer_name = booking.get('customer_name', '').split('\n')[0].replace('★', '').strip()
            phone = booking.get('phone', '')
            visit_dt = booking.get('visit_datetime', '')
            # visit_datetime形式: 2025-12-16 11:30:00
            time = visit_dt.split(' ')[1][:5] if visit_dt and ' ' in visit_dt else ''
            menu = booking.get('menu', '')
            
            # 顧客を検索
            customer = None
            if phone and phone in phone_to_customer:
                customer = phone_to_customer[phone]
            else:
                normalized = customer_name.replace(" ", "").replace("　", "").replace("★", "").strip()
                if normalized in name_to_customer:
                    customer = name_to_customer[normalized]
            
            if not customer or not customer.get('line_user_id'):
                results[label]["no_match"] += 1
                continue
            
            # メッセージ作成
            # 日時フォーマット
            def format_dt(dt_str):
                # 新形式: 2025-12-16 11:30:00
                if " " in dt_str and "-" in dt_str:
                    parts = dt_str.split(" ")
                    date_part = parts[0]  # 2025-12-16
                    time_part = parts[1][:5]  # 11:30
                    y, month, day = date_part.split("-")
                    from datetime import date
                    weekdays = ["月", "火", "水", "木", "金", "土", "日"]
                    d = date(int(y), int(month), int(day))
                    return f"{int(month)}月{int(day)}日({weekdays[d.weekday()]}){time_part}〜"
                # 旧形式: 12/16 11:30
                m = re.match(r'(\d+)/(\d+)(\d{2}:\d{2})', dt_str)
                if m:
                    month, day, tm = m.groups()
                    from datetime import date
                    weekdays = ['月', '火', '水', '木', '金', '土', '日']
                    d = date(2025, int(month), int(day))
                    return f"{month}月{day}日({weekdays[d.weekday()]}){tm}〜"
                return dt_str
            
            # メニュークリーンアップ
            def clean_menu(m):
                has_off_shampoo = 'オフあり+アイシャンプー' in m or 'オフあり＋アイシャンプー' in m
                exclude = ['【全員】', '【次回】', '【リピーター様】', '【4週間以内】', '【ご新規】',
                    'オフあり+アイシャンプー', 'オフあり＋アイシャンプー', '次世代まつ毛パーマ', 'ダメージレス',
                    '(4週間以内 )', '(4週間以内)', '(アイシャンプー・トリートメント付き)', '(SP・TR付)',
                    '(コーティング・シャンプー・オフ込)', '(まゆげパーマ)', '(眉毛Wax)', '＋メイク付', '+メイク付',
                    '指名料', 'カラー変更', '束感★']
                for w in exclude:
                    m = m.replace(w, '')
                m = re.sub(r'\(ｸｰﾎﾟﾝ\)', '', m)
                m = re.sub(r'《[^》]*》', '', m)
                m = re.sub(r'【[^】]*】', '', m)
                m = re.sub(r'◇エクステ.*', '', m)
                m = re.sub(r'◇毛量調整.*', '', m)
                m = re.sub(r'[¥￥][0-9,]+', '', m)
                m = re.sub(r'^◇', '', m)
                m = re.sub(r'◇$', '', m)
                m = re.sub(r'◇\s*$', '', m)
                parts = m.split('◇')
                cleaned = [p.strip().strip('　') for p in parts if p.strip()]
                m = '＋'.join(cleaned) if cleaned else ''
                m = re.sub(r'\s+', ' ', m).strip()
                if has_off_shampoo and m:
                    m = f'{m}（オフあり+アイシャンプー）'
                return m
            
            formatted_dt = format_dt(visit_dt)
            cleaned_menu = clean_menu(menu)
            
            if days == 3:
                # テストモード: 神原のみに送信
                KANBARA_PHONE = "09015992055"
                message = f"""{customer_name} 様

ご予約【3日前】のお知らせ🕊️
【本店】
{formatted_dt}
{cleaned_menu}

下記はすべてのお客様に気持ちよくご利用いただくためのご案内です。
ご理解とご協力をお願いいたします🙇‍♀️


■ 遅刻について
スタッフ判断でメニュー変更や日時変更となる場合があり
当日中の時間変更であれば、【次回予約特典】はそのまま適用可能

＜次回予約特典が失効＞
◉予約日から3日前まで
※ご予約日の前倒し・同日時間変更は適用のまま
◉前回来店日から3ヶ月経過

＜キャンセル料＞
◾️次回予約特典
当日変更：施術代金の50％
◾️通常予約
前日変更：施術代金の50％
当日変更：施術代金の100％"""
            else:
                message = f"""{customer_name} 様
ご予約日の【7日前】となりました🕊️
{formatted_dt}
{cleaned_menu}

「マツエクが残っている」
「カールが残っている」
「眉毛の手入れをした…」
「仕事が入った」
など、ご予約日延期は、お早めにご協力をお願いします✨

＜次回予約特典が失効＞
◉予約日から3日前まで
※ご予約日の前倒し・同日時間変更は適用のまま
◉前回来店日から3ヶ月経過

＜キャンセル料＞
◾️次回予約特典
当日変更：施術代金の50％
◾️通常予約
前日変更：施術代金の50％
当日変更：施術代金の100％"""
      
            # 重複送信チェック
            today_str = today.strftime("%Y-%m-%d")
            dup_check = requests.get(
                f'{SUPABASE_URL}/rest/v1/reminder_logs?phone=eq.{phone}&days_ahead=eq.{days}&sent_at=gte.{today_str}T00:00:00',
                headers=headers
            )
            if dup_check.json():
                continue  # 既に今日送信済み
            
            # テストモード: 神原以外はスキップ
            if test_mode and phone != KAMBARA_PHONE:
                continue
            
            # LINE送信
            if send_line_message(customer['line_user_id'], message):
                results[label]["sent"] += 1
                status = "sent"
            else:
                results[label]["failed"] += 1
                status = "failed"
            
            # ログ保存
            requests.post(
                f'{SUPABASE_URL}/rest/v1/reminder_logs',
                headers=headers,
                json={'phone': phone, 'customer_name': customer_name, 'days_ahead': days, 'status': status}
            )
            
            # 神原に送信通知
            if status == "sent":
                notify_message = f"✅ リマインド送信完了\n{customer_name}様（{days}日前）"
                send_line_message("U9022782f05526cf7632902acaed0cb08", notify_message)
    
    return results
# ========== 8週間予約スクレイピング ==========
@app.route('/api/scrape_8weeks', methods=['GET', 'POST'])
def scrape_8weeks():
    """8週間分の予約をスクレイピングしてbookingsテーブルに保存"""
    from datetime import datetime, timedelta, timezone
    from playwright.sync_api import sync_playwright
    import re
    import json
    import re
    
    JST = timezone(timedelta(hours=9))
    today = datetime.now(JST)
    
    results = {"total": 0, "updated": 0, "errors": []}
    
    headers = {
        'apikey': SUPABASE_KEY,
        'Authorization': f'Bearer {SUPABASE_KEY}',
        'Content-Type': 'application/json',
        'Prefer': 'resolution=merge-duplicates'
    }
    
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context()
            
            # クッキー読み込み
            cookie_file = os.path.join(os.path.dirname(__file__), 'session_cookies.json')
            if os.path.exists(cookie_file):
                with open(cookie_file, 'r') as f:
                    cookies = json.load(f)
                    context.add_cookies(cookies)
            
            page = context.new_page()
            
            # 8週間分（56日）をループ
            for day_offset in range(56):
                target_date = today + timedelta(days=day_offset)
                date_str = target_date.strftime("%Y%m%d")
                url = f"https://salonboard.com/KLP/reserve/reserveList/?search_date={date_str}"
                
                try:
                    page.goto(url, timeout=30000, wait_until="domcontentloaded")
                    page.wait_for_timeout(2000)
                    
                    # ログインチェック
                    if 'login' in page.url.lower():
                        results["errors"].append(f"ログイン必要: {date_str}")
                        break
                    
                    # 予約データ抽出
                    rows = page.query_selector_all('tr.rsv')
                    
                    for row in rows:
                        try:
                            time_el = row.query_selector('td.time')
                            name_el = row.query_selector('td.name a')
                            phone_el = row.query_selector('td.phone')
                            menu_el = row.query_selector('td.menu')
                            staff_el = row.query_selector('td.staff')
                            
                            visit_time = time_el.inner_text().strip() if time_el else ''
                            customer_name = name_el.inner_text().strip() if name_el else ''
                            phone = phone_el.inner_text().strip() if phone_el else ''
                            menu = menu_el.inner_text().strip() if menu_el else ''
                            staff = staff_el.inner_text().strip() if staff_el else ''
                            
                            if not customer_name:
                                continue
                            
                            # booking_id生成（重複防止用）
                            booking_id = f"{date_str}_{visit_time}_{phone}".replace(" ", "").replace(":", "")
                            
                            data = {
                                'booking_id': booking_id,
                                'customer_name': customer_name.replace('★', '').strip(),
                                'phone': re.sub(r'[^\d]', '', phone),
                                'visit_datetime': f"{target_date.strftime('%m/%d')}{visit_time}",
                                'menu': menu,
                                'staff': staff,
                                'status': 'confirmed',
                                'booking_source': 'salonboard'
                            }
                            
                            # Upsert
                            res = requests.post(
                                f'{SUPABASE_URL}/rest/v1/bookings',
                                headers=headers,
                                json=data
                            )
                            
                            if res.status_code in [200, 201]:
                                results["updated"] += 1
                            
                            results["total"] += 1
                            
                        except Exception as e:
                            continue
                    
                except Exception as e:
                    results["errors"].append(f"{date_str}: {str(e)}")
                    continue
            
            browser.close()
    
    except Exception as e:
        results["errors"].append(str(e))
    
    return jsonify(results)

@app.route('/api/scrape_test_1day', methods=['GET', 'POST'])
def scrape_test_1day():
    """テスト用：1日分のみスクレイピング"""
    from datetime import datetime, timedelta, timezone
    from playwright.sync_api import sync_playwright
    import re
    import json
    import re
    
    JST = timezone(timedelta(hours=9))
    today = datetime.now(JST)
    target_date = today + timedelta(days=3)  # 3日後
    date_str = target_date.strftime("%Y%m%d")
    
    results = {"date": target_date.strftime("%Y-%m-%d"), "bookings": [], "error": None}
    
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context()
            
            cookie_file = os.path.join(os.path.dirname(__file__), 'session_cookies.json')
            if os.path.exists(cookie_file):
                with open(cookie_file, 'r') as f:
                    cookies = json.load(f)
                    context.add_cookies(cookies)
            
            page = context.new_page()
            url = f"https://salonboard.com/KLP/reserve/reserveList/?search_date={date_str}"
            
            page.goto(url, timeout=30000, wait_until="domcontentloaded")
            page.wait_for_timeout(3000)
            
            if 'login' in page.url.lower():
                results["error"] = "ログイン必要（クッキー期限切れ）"
            else:
                rows = page.query_selector_all('tr.rsv')
                for row in rows:
                    try:
                        time_el = row.query_selector('td.time')
                        name_el = row.query_selector('td.name a')
                        results["bookings"].append({
                            "time": time_el.inner_text().strip() if time_el else '',
                            "name": name_el.inner_text().strip() if name_el else ''
                        })
                    except:
                        continue
                
                results["total"] = len(results["bookings"])
            
            browser.close()
    
    except Exception as e:
        results["error"] = str(e)
    
    return jsonify(results)

@app.route('/api/scrape_test_1day_v2', methods=['GET', 'POST'])
def scrape_test_1day_v2():
    """テスト用：1日分のみ（タイムアウト延長）"""
    from datetime import datetime, timedelta, timezone
    from playwright.sync_api import sync_playwright
    import re
    import json
    
    JST = timezone(timedelta(hours=9))
    today = datetime.now(JST)
    target_date = today + timedelta(days=3)
    date_str = target_date.strftime("%Y%m%d")
    
    results = {"date": target_date.strftime("%Y-%m-%d"), "bookings": [], "error": None, "url": None}
    
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context()
            
            cookie_file = os.path.join(os.path.dirname(__file__), 'session_cookies.json')
            if os.path.exists(cookie_file):
                with open(cookie_file, 'r') as f:
                    cookies = json.load(f)
                    context.add_cookies(cookies)
            
            page = context.new_page()
            
            # まずトップページ
            page.goto("https://salonboard.com/", timeout=60000, wait_until="domcontentloaded")
            page.wait_for_timeout(2000)
            
            # 予約ページ
            url = f"https://salonboard.com/KLP/reserve/reserveList/?search_date={date_str}"
            results["url"] = url
            
            page.goto(url, timeout=90000, wait_until="domcontentloaded")
            page.wait_for_timeout(3000)
            
            results["current_url"] = page.url
            
            if 'login' in page.url.lower():
                results["error"] = "ログイン必要"
            else:
                # ページタイトル取得
                results["title"] = page.title()
                
                # 予約行を取得
                rows = page.query_selector_all('tr.rsv')
                results["row_count"] = len(rows)
                
                for row in rows[:5]:  # 最初の5件のみ
                    try:
                        time_el = row.query_selector('td.time')
                        name_el = row.query_selector('td.name a')
                        results["bookings"].append({
                            "time": time_el.inner_text().strip() if time_el else '',
                            "name": name_el.inner_text().strip() if name_el else ''
                        })
                    except:
                        continue
            
            browser.close()
    
    except Exception as e:
        results["error"] = str(e)
    
    return jsonify(results)

@app.route('/api/scrape_8weeks_v2', methods=['GET', 'POST'])
def api_scrape_8weeks_v2():
    """8週間分の予約をスクレイピング（バックグラウンド実行）"""
    import threading
    import subprocess
    
    def run_scrape():
        subprocess.run(['python3', 'scrape_8weeks_v2.py'], capture_output=True, text=True)
    
    thread = threading.Thread(target=run_scrape)
    thread.start()
    
    return jsonify({'success': True, 'message': 'スクレイピング開始（バックグラウンド実行中）'})

# 8週間スクレイピング実行中フラグ
scrape_8weeks_running = False

@app.route('/api/scrape_8weeks_v3', methods=['GET', 'POST'])
def api_scrape_8weeks_v3():
    """8週間分の予約をスクレイピング（二重実行防止付き）"""
    global scrape_8weeks_running
    
    # 二重実行防止
    if scrape_8weeks_running:
        return jsonify({'success': False, 'message': '既に実行中です。しばらくお待ちください。'}), 429
    
    import threading
    import subprocess
    
    def run_scrape():
        global scrape_8weeks_running
        scrape_8weeks_running = True
        try:
            subprocess.run(['python3', 'scrape_8weeks_v3.py'], timeout=1800)
        except Exception as e:
            print(f"スクレイピングエラー: {e}")
        finally:
            scrape_8weeks_running = False
    
    thread = threading.Thread(target=run_scrape)
    thread.start()
    
    return jsonify({'success': True, 'message': 'スクレイピング開始（バックグラウンド実行中）'})

# ========== CSVインポート機能 ==========
@app.route('/api/import-customers', methods=['POST'])
def api_import_customers():
    """サロンボードのCSVから顧客情報をインポート"""
    import csv
    import io
    
    if 'file' not in request.files:
        return jsonify({'error': 'ファイルがありません'}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'ファイルが選択されていません'}), 400
    
    try:
        stream = io.StringIO(file.stream.read().decode('utf-8-sig'))
        reader = csv.DictReader(stream)
        
        headers_api = {
            'apikey': SUPABASE_KEY,
            'Authorization': f'Bearer {SUPABASE_KEY}',
            'Content-Type': 'application/json'
        }
        
        updated = 0
        for row in reader:
            phone = row.get('電話番号', '').replace('-', '').replace(' ', '')
            name = row.get('顧客名', '') or row.get('お客様名', '') or row.get('名前', '')
            
            if phone and name:
                # 電話番号でcustomersを検索して名前を更新
                res = requests.get(
                    f'{SUPABASE_URL}/rest/v1/customers?phone=eq.{phone}&select=id',
                    headers=headers_api
                )
                customers = res.json()
                
                if customers:
                    # 既存顧客の名前を更新
                    requests.patch(
                        f'{SUPABASE_URL}/rest/v1/customers?phone=eq.{phone}',
                        headers=headers_api,
                        json={'name': name}
                    )
                    updated += 1
        
        return jsonify({'success': True, 'updated': updated})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ========== LIFF予約確認画面 ==========
@app.route('/liff/booking')
def liff_booking():
    """LIFF予約確認画面"""
    liff_id = "2006629229-Y8lb2daA"
    html = f'''<!DOCTYPE html>
<html lang="ja">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>予約確認</title>
    <script src="https://static.line-scdn.net/liff/edge/2/sdk.js"></script>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ font-family: -apple-system, BlinkMacSystemFont, sans-serif; background: #f5f5f5; }}
        .container {{ max-width: 500px; margin: 0 auto; padding: 20px; }}
        .header {{ background: #06c755; color: white; padding: 20px; text-align: center; border-radius: 10px 10px 0 0; }}
        .content {{ background: white; padding: 20px; border-radius: 0 0 10px 10px; }}
        .booking-card {{ border: 1px solid #ddd; border-radius: 8px; padding: 15px; margin: 10px 0; }}
        .booking-date {{ font-size: 18px; font-weight: bold; color: #333; }}
        .booking-menu {{ font-size: 14px; color: #666; margin: 5px 0; }}
        .btn {{ display: block; width: 100%; padding: 12px; margin: 5px 0; border: none; border-radius: 5px; font-size: 14px; cursor: pointer; }}
        .btn-change {{ background: #06c755; color: white; }}
        .btn-cancel {{ background: #ff6b6b; color: white; }}
        .btn-submit {{ background: #06c755; color: white; }}
        .loading {{ text-align: center; padding: 40px; }}
        .no-booking {{ text-align: center; padding: 40px; color: #666; }}
        .user-info {{ background: #e8f5e9; padding: 10px; border-radius: 5px; margin-bottom: 15px; }}
        .phone-form {{ padding: 20px 0; }}
        .phone-form input {{ width: 100%; padding: 15px; font-size: 18px; border: 2px solid #ddd; border-radius: 8px; margin: 10px 0; }}
        .phone-form label {{ font-size: 14px; color: #666; }}
        .phone-note {{ font-size: 12px; color: #999; margin-top: 10px; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>予約確認</h1>
        </div>
        <div class="content">
            <div id="user-info" class="user-info" style="display:none;"></div>
            <div id="loading" class="loading">読み込み中...</div>
            <div id="phone-form" class="phone-form" style="display:none;">
                <label>電話番号を入力してください</label>
                <input type="tel" id="phone-input" placeholder="09012345678" pattern="[0-9]*">
                <button class="btn btn-submit" onclick="submitPhone()">予約を確認</button>
                <p class="phone-note">※ サロンボードにご登録の電話番号を入力してください<br>※ 初回のみ入力が必要です</p>
            </div>
            <div id="bookings"></div>
        </div>
    </div>
    <script>
        const LIFF_ID = "{liff_id}";
        const API_BASE = "https://salon-absence-system-production.up.railway.app";
        
        function formatDate(dateStr) {{
    const match = dateStr.match(/(\d{{4}})[-\/](\d{{2}})[-\/](\d{{2}}).*?(\d{{2}}):(\d{{2}})/);
    if (match) {{
        const year = match[1];
        const month = parseInt(match[2]);
        const day = parseInt(match[3]);
        const hour = match[4];
        const min = match[5];
        const date = new Date(year, month - 1, day);
        const days = ['日', '月', '火', '水', '木', '金', '土'];
        const dayOfWeek = days[date.getDay()];
        return `${{month}}月${{day}}日(${{dayOfWeek}}) ${{hour}}:${{min}}〜`;
    }}
    return dateStr;
}}
        let userProfile = null;
        let lineUserId = null;
        
        async function initLiff() {{
            try {{
                document.getElementById('loading').innerHTML = 'LIFF初期化中...';
                await liff.init({{ liffId: LIFF_ID }});
                
                if (!liff.isLoggedIn()) {{
                    document.getElementById('loading').innerHTML = 'ログイン中...';
                    liff.login();
                    return;
                }}
                
                document.getElementById('loading').innerHTML = 'プロフィール取得中...';
                userProfile = await liff.getProfile();
                lineUserId = userProfile.userId;
                document.getElementById('user-info').innerHTML = `<strong>${{userProfile.displayName}}</strong> 様`;
                document.getElementById('user-info').style.display = 'block';
                
                await checkRegistration(lineUserId);
            }} catch (error) {{
                document.getElementById('loading').innerHTML = 'エラー: ' + error.message + '<br><br><button onclick="location.reload()">再読み込み</button>';
                console.error('LIFF init error:', error);
            }}
        }}
        
        async function checkRegistration(lineUserId) {{
            try {{
                document.getElementById('loading').innerHTML = '確認中...';
                const response = await fetch(`/api/liff/check-registration?line_user_id=${{lineUserId}}`);
                const data = await response.json();
                
                document.getElementById('loading').style.display = 'none';
                
                if (data.registered && data.phone) {{
                    await loadBookings(data.phone);
                }} else {{
                    document.getElementById('phone-form').style.display = 'block';
                }}
            }} catch (error) {{
                document.getElementById('loading').style.display = 'none';
                document.getElementById('phone-form').style.display = 'block';
                console.error('Check registration error:', error);
            }}
        }}
        
        async function submitPhone() {{
            const phone = document.getElementById('phone-input').value.replace(/[^0-9]/g, '');
            
            if (phone.length < 10) {{
                alert('正しい電話番号を入力してください');
                return;
            }}
            
            try {{
                // 電話番号をLINE IDと紐付けて保存
                const response = await fetch(API_BASE + '/api/liff/register-phone', {{
                    method: 'POST',
                    headers: {{ 'Content-Type': 'application/json' }},
                    body: JSON.stringify({{ line_user_id: lineUserId, phone: phone }})
                }});
                const data = await response.json();
                
                if (data.success) {{
                    document.getElementById('phone-form').style.display = 'none';
                    await loadBookings(phone);
                }} else {{
                    alert(data.message || '登録に失敗しました');
                }}
            }} catch (error) {{
                alert('エラーが発生しました');
            }}
        }}
        
        async function loadBookings(phone) {{
            try {{
                const response = await fetch(`/api/liff/bookings-by-phone?phone=${{phone}}`);
                const data = await response.json();
                
                if (data.bookings && data.bookings.length > 0) {{
                    let html = '';
                    data.bookings.forEach(booking => {{
                        html += `
                            <div class="booking-card">
                                <div class="booking-date">${{formatDate(booking.visit_datetime)}}</div>
                                <div class="booking-menu">メニュー：${{booking.menu || '未設定'}}</div>
                                <div class="booking-menu">指名：${{booking.staff || 'なし'}}</div>
                                <button class="btn btn-change" onclick="changeBooking('${{booking.booking_id}}')">日時変更</button>
                                <button class="btn btn-cancel" onclick="cancelBooking('${{booking.booking_id}}')">キャンセル</button>
                            </div>
                        `;
                    }});
                    document.getElementById('bookings').innerHTML = html;
                }} else {{
                    document.getElementById('bookings').innerHTML = '<div class="no-booking">現在予約はありません</div>';
                }}
            }} catch (error) {{
                document.getElementById('bookings').innerHTML = '<div class="no-booking">予約の取得に失敗しました</div>';
            }}
        }}
        
        let calendarData = {{}};
        let currentBookingId = null;
        let currentBookingMenu = '';
        let currentBookingDuration = 60;
        let currentWeek = 0;
        
        async function changeBooking(bookingId) {{
            currentBookingId = bookingId;
            
            // ローディング表示
            document.getElementById('bookings').innerHTML = `
                <div style="text-align:center;padding:60px 20px;">
                    <div style="width:50px;height:50px;border:4px solid #f3f3f3;border-top:4px solid #c44d6e;border-radius:50%;animation:spin 1s linear infinite;margin:0 auto 20px;"></div>
                    <p style="color:#666;font-size:14px;">読み込み中...</p>
                </div>
                <style>@keyframes spin {{ 0% {{ transform: rotate(0deg); }} 100% {{ transform: rotate(360deg); }} }}</style>
            `;
            
            // 現在の予約情報を取得
            const bookingCard = document.querySelector(`[data-booking-id="${{bookingId}}"]`) || document.querySelector('.booking-card');
            if (bookingCard) {{
                const menuEl = bookingCard.querySelector('.booking-menu');
                currentBookingMenu = menuEl ? menuEl.innerText.replace('メニュー：', '') : '未設定';
            }}

            // 所要時間をSalonBoardから取得
            try {{
                const durationRes = await fetch(API_BASE + '/api/liff/get-duration', {{
                    method: 'POST',
                    headers: {{'Content-Type': 'application/json'}},
                    body: JSON.stringify({{booking_id: bookingId}})
                }});
                const durationData = await durationRes.json();
                currentBookingDuration = durationData.duration || 60;
            }} catch (e) {{
                currentBookingDuration = 60;
            }}
            
            // メニュー選択画面を表示
            document.getElementById('bookings').innerHTML = `
                <div id="menu-selection" style="font-family:-apple-system,BlinkMacSystemFont,sans-serif;">
                    <div style="background:#f8e0e6;padding:15px;border-radius:8px;margin-bottom:15px;">
                        <div style="color:#c44d6e;font-weight:bold;margin-bottom:10px;">選択済みクーポン・メニュー</div>
                        <div style="background:#fff;padding:12px;border-radius:5px;border-left:4px solid #c44d6e;">
                            <span style="background:#c44d6e;color:#fff;font-size:10px;padding:2px 6px;border-radius:3px;margin-right:8px;">継続</span>
                            <span style="font-size:14px;">${{currentBookingMenu}}</span>
                        </div>
                        <p style="font-size:11px;color:#666;margin-top:8px;">※メニューは変更せず、日時のみ変更します</p>
                    </div>
                    
                    <div style="display:flex;align-items:center;gap:15px;margin-bottom:15px;padding:10px;background:#f5f5f5;border-radius:5px;">
                        <span style="font-size:13px;">所要時間合計（目安）</span>
                        <select id="duration-select" style="padding:8px 12px;border:1px solid #ddd;border-radius:5px;font-size:14px;" onchange="updateDuration()">
                            <option value="30">30分</option>
                            <option value="60" selected>1時間</option>
                            <option value="90">1時間30分</option>
                            <option value="120">2時間</option>
                            <option value="150">2時間30分</option>
                        </select>
                    </div>
                    
                    <div style="margin-bottom:15px;">
                        <span style="font-size:13px;margin-right:15px;">スタッフ：</span>
                        <label style="margin-right:15px;"><input type="radio" name="staff-pref" value="no" checked> 指名しない</label>
                        <label><input type="radio" name="staff-pref" value="yes" disabled> 指名する</label>
                    </div>
                    
                    <button class="btn btn-change" style="width:100%;padding:12px;font-size:16px;" onclick="showCalendar()">空き状況を確認する</button>
                    <button class="btn" style="background:#999;color:white;margin-top:10px;width:100%;padding:12px;" onclick="location.reload()">戻る</button>
                </div>
            `;
        }}
        
        function updateDuration() {{
            currentBookingDuration = parseInt(document.getElementById('duration-select').value);
        }}
        
        async function showCalendar() {{
            document.getElementById('bookings').innerHTML = `
                <div id="calendar-view" style="font-family:-apple-system,BlinkMacSystemFont,sans-serif;">
                    <div style="background:#f8e0e6;padding:12px;border-radius:8px;margin-bottom:15px;">
                        <div style="font-size:12px;color:#666;">選択中のメニュー</div>
                        <div style="font-size:14px;font-weight:bold;">${{currentBookingMenu}}</div>
                        <div style="font-size:12px;color:#c44d6e;margin-top:5px;">所要時間: ${{currentBookingDuration}}分</div>
                    </div>
                    
                    <div style="display:flex;border-bottom:2px solid #ddd;margin-bottom:15px;">
                        <div style="flex:1;text-align:center;padding:10px;border-bottom:2px solid #c44d6e;margin-bottom:-2px;font-weight:bold;color:#c44d6e;">サロンの空き状況</div>
                    </div>
                    
                    <div id="calendar-loading" style="text-align:center;padding:20px;">読み込み中...</div>
                    
                    <div id="week-nav" style="display:none;margin-bottom:10px;">
                        <div style="display:flex;justify-content:space-between;align-items:center;">
                            <button onclick="changeWeek(-1)" style="padding:8px 15px;border:1px solid #ddd;border-radius:5px;background:#fff;cursor:pointer;">< 前の一週間</button>
                            <span id="month-label" style="font-size:16px;font-weight:bold;"></span>
                            <button onclick="changeWeek(1)" style="padding:8px 15px;border:1px solid #ddd;border-radius:5px;background:#fff;cursor:pointer;">次の一週間 ></button>
                        </div>
                    </div>
                    
                    <div id="calendar-table" style="overflow-x:auto;"></div>
                    
                    <div style="margin-top:15px;padding:10px;background:#f5f5f5;border-radius:5px;font-size:11px;color:#666;">
                        <p>◯ の日時から施術を開始することが出来ます。</p>
                        <p>ご希望の来店日時の ◯ を選択してください。</p>
                    </div>
                    
                    <button class="btn" style="background:#999;color:white;margin-top:15px;width:100%;padding:12px;" onclick="location.reload()">戻る</button>
                </div>
            `;
            await loadCalendarData();
            renderCalendar();
        }}
        
        async function loadCalendarData() {{
            try {{
                const res = await fetch(API_BASE + '/api/liff/available-slots-range');
                const data = await res.json();
                if (data.dates) {{
                    calendarData = data.dates;
                }}
            }} catch (e) {{
                console.error('空き枠取得エラー', e);
            }}
            document.getElementById('calendar-loading').style.display = 'none';
            document.getElementById('week-nav').style.display = 'block';
        }}
        
        function changeWeek(delta) {{
            currentWeek += delta;
            if (currentWeek < 0) currentWeek = 0;
            if (currentWeek > 1) currentWeek = 1;
            renderCalendar();
        }}
        
        function renderCalendar() {{
            const today = new Date();
            const startIdx = currentWeek * 7;
            const dates = [];
            for (let i = startIdx; i < startIdx + 7 && i < 14; i++) {{
                const d = new Date(today);
                d.setDate(today.getDate() + i);
                dates.push(d);
            }}
            
            document.getElementById('month-label').innerText = `${{today.getFullYear()}}年${{dates[0].getMonth()+1}}月`;
            
            const timeSlots = [];
            for (let h = 9; h < 19; h++) {{
                for (let m = 0; m < 60; m += 10) {{
                    if (h === 18 && m > 50) continue;
                    timeSlots.push(`${{h}}:${{m.toString().padStart(2, '0')}}`);
                }}
            }}
            
            const days = ['日', '月', '火', '水', '木', '金', '土'];
            const requiredMinutes = currentBookingDuration;
            
            let html = '<table style="border-collapse:collapse;font-size:12px;width:100%;">';
            html += '<thead><tr><th style="border:1px solid #ddd;padding:8px;background:#f5f5f5;width:60px;"></th>';
            
            dates.forEach(d => {{
                const day = days[d.getDay()];
                const color = d.getDay() === 0 ? '#e74c3c' : d.getDay() === 6 ? '#3498db' : '#333';
                html += `<th style="border:1px solid #ddd;padding:8px;background:#f5f5f5;color:${{color}};text-align:center;">
                    <div style="font-size:16px;font-weight:bold;">${{d.getDate()}}</div>
                    <div style="font-size:11px;">(${{day}})</div>
                </th>`;
            }});
            html += '</tr></thead><tbody>';
            
            timeSlots.forEach(time => {{
                html += `<tr><td style="border:1px solid #ddd;padding:6px 8px;background:#f5f5f5;font-weight:bold;text-align:right;">${{time}}</td>`;
                
                dates.forEach(d => {{
                    const dateStr = `${{d.getFullYear()}}${{(d.getMonth()+1).toString().padStart(2,'0')}}${{d.getDate().toString().padStart(2,'0')}}`;
                    const dayData = calendarData[dateStr];
                    let cellContent = '×';
                    let cellStyle = 'color:#ccc;';
                    
                    if (dayData && !dayData.error && dayData.staff_schedules) {{
                        let hasEnoughSlot = false;
                        
                        dayData.staff_schedules.forEach(staff => {{
                            if (!staff.is_day_off && staff.available_slots) {{
                                staff.available_slots.forEach(slot => {{
                                    const slotStartParts = slot.start.split(':');
                                    const slotEndParts = slot.end.split(':');
                                    const slotStartMin = parseInt(slotStartParts[0]) * 60 + parseInt(slotStartParts[1]);
                                    const slotEndMin = parseInt(slotEndParts[0]) * 60 + parseInt(slotEndParts[1]);
                                    const slotDuration = slotEndMin - slotStartMin;
                                    
                                    const timeParts = time.split(':');
                                    const timeMin = parseInt(timeParts[0]) * 60 + parseInt(timeParts[1]);
                                    
                                    if (timeMin >= slotStartMin && timeMin + requiredMinutes <= slotEndMin) {{
                                        hasEnoughSlot = true;
                                    }}
                                }});
                            }}
                        }});
                        
                        if (hasEnoughSlot) {{
                            cellContent = `<a href="#" onclick="selectSlot('${{currentBookingId}}','${{dateStr}}','${{time}}');return false;" style="color:#e74c3c;font-weight:bold;text-decoration:none;font-size:16px;">◯</a>`;
                            cellStyle = 'background:#fff;';
                        }} else {{
                            cellContent = '×';
                            cellStyle = 'color:#ccc;background:#f9f9f9;';
                        }}
                    }} else {{
                        cellContent = 'ー';
                        cellStyle = 'color:#999;background:#f0f0f0;';
                    }}
                    
                    html += `<td style="border:1px solid #ddd;padding:8px;text-align:center;${{cellStyle}}">${{cellContent}}</td>`;
                }});
                html += '</tr>';
            }});
            
            html += '</tbody></table>';
            document.getElementById('calendar-table').innerHTML = html;
        }}
        
        async function selectSlot(bookingId, dateStr, time) {{
            const dateFormatted = `${{dateStr.slice(0,4)}}/${{dateStr.slice(4,6)}}/${{dateStr.slice(6,8)}}`;
            if (confirm(`${{dateFormatted}} ${{time}}〜 に変更しますか？`)) {{
                document.getElementById('calendar-table').innerHTML = '<p style="text-align:center;padding:20px;">変更処理中...</p>';
                const response = await fetch(API_BASE + '/api/liff/execute-change', {{
                    method: 'POST',
                    headers: {{ 'Content-Type': 'application/json' }},
                    body: JSON.stringify({{ booking_id: bookingId, new_date: dateStr, new_time: time, line_user_id: lineUserId }})
                }});
                const data = await response.json();
                alert(data.message || '変更リクエストを送信しました');
                if (data.success) location.reload();
            }}
        }}
        
        async function cancelBooking(bookingId) {{
            if (confirm('本当にキャンセルしますか？')) {{
                const response = await fetch(API_BASE + '/api/liff/cancel-request', {{
                    method: 'POST',
                    headers: {{ 'Content-Type': 'application/json' }},
                    body: JSON.stringify({{ booking_id: bookingId, line_user_id: lineUserId }})
                }});
                const data = await response.json();
                alert(data.message || 'キャンセルリクエストを送信しました');
                if (data.success) {{
                    location.reload();
                }}
            }}
        }}
        
        initLiff();
    </script>
</body>
</html>'''
    return html

@app.route('/api/liff/check-registration')
def api_liff_check_registration():
    """LINE IDで電話番号登録状況を確認"""
    line_user_id = request.args.get('line_user_id')
    
    if not line_user_id:
        return jsonify({'registered': False})
    
    headers = {
        'apikey': SUPABASE_KEY,
        'Authorization': f'Bearer {SUPABASE_KEY}'
    }
    
    res = requests.get(
        f'{SUPABASE_URL}/rest/v1/customers?line_user_id=eq.{line_user_id}&select=phone',
        headers=headers
    )
    customers = res.json()
    
    if customers and customers[0].get('phone'):
        return jsonify({'registered': True, 'phone': customers[0]['phone']})
    else:
        return jsonify({'registered': False})

@app.route('/api/liff/register-phone', methods=['POST'])
def api_liff_register_phone():
    """電話番号をLINE IDと紐付け"""
    data = request.json
    line_user_id = data.get('line_user_id')
    phone = data.get('phone', '').replace('-', '').replace(' ', '')
    
    if not line_user_id or not phone:
        return jsonify({'success': False, 'message': '入力が不正です'})
    
    headers = {
        'apikey': SUPABASE_KEY,
        'Authorization': f'Bearer {SUPABASE_KEY}',
        'Content-Type': 'application/json'
    }
    
    # LINE IDで既存顧客を検索
    res = requests.get(
        f'{SUPABASE_URL}/rest/v1/customers?line_user_id=eq.{line_user_id}&select=id',
        headers=headers
    )
    customers = res.json()
    
    if customers:
        # 既存顧客の電話番号を更新
        requests.patch(
            f'{SUPABASE_URL}/rest/v1/customers?line_user_id=eq.{line_user_id}',
            headers=headers,
            json={'phone': phone}
        )
    else:
        # 新規顧客として登録
        requests.post(
            f'{SUPABASE_URL}/rest/v1/customers',
            headers=headers,
            json={'line_user_id': line_user_id, 'phone': phone}
        )
    
    return jsonify({'success': True})

@app.route('/api/liff/bookings-by-phone')
def api_liff_bookings_by_phone():
    """電話番号で予約を検索（8weeks_bookingsテーブル）"""
    from datetime import datetime, timedelta, timezone
    
    phone = request.args.get('phone', '').replace('-', '').replace(' ', '')
    
    if not phone:
        return jsonify({'bookings': []})
    
    headers = {
        'apikey': SUPABASE_KEY,
        'Authorization': f'Bearer {SUPABASE_KEY}'
    }
    
    # 8weeks_bookingsテーブルで電話番号検索
    res = requests.get(
        f'{SUPABASE_URL}/rest/v1/8weeks_bookings?phone=eq.{phone}&select=booking_id,visit_datetime,customer_name,menu,staff&order=visit_datetime.asc',
        headers=headers
    )
    all_bookings = res.json()
    
    # 今日以降のみフィルタ（Python側）
    JST = timezone(timedelta(hours=9))
    today = datetime.now(JST).strftime('%Y-%m-%d')
    
    bookings = [b for b in all_bookings if b.get('visit_datetime', '') >= today]
    
    # メニュークリーンアップ
    def clean_menu(m):
        import re
        if not m:
            return ''
        has_off_shampoo = 'オフあり+アイシャンプー' in m or 'オフあり＋アイシャンプー' in m
        exclude = ['【全員】', '【次回】', '【リピーター様】', '【4週間以内】', '【ご新規】',
            'オフあり+アイシャンプー', 'オフあり＋アイシャンプー', '次世代まつ毛パーマ', 'ダメージレス',
            '(4週間以内 )', '(4週間以内)', '(アイシャンプー・トリートメント付き)', '(SP・TR付)',
            '(コーティング・シャンプー・オフ込)', '(まゆげパーマ)', '(眉毛Wax)', '＋メイク付', '+メイク付',
            '指名料', 'カラー変更', '束感★']
        for w in exclude:
            m = m.replace(w, '')
        m = re.sub(r'\(ｸｰﾎﾟﾝ\)', '', m)
        m = re.sub(r'《[^》]*》', '', m)
        m = re.sub(r'【[^】]*】', '', m)
        m = re.sub(r'◇エクステ.*', '', m)
        m = re.sub(r'◇毛量調整.*', '', m)
        m = re.sub(r'[¥￥][0-9,]+', '', m)
        m = re.sub(r'^◇', '', m)
        m = re.sub(r'◇$', '', m)
        m = re.sub(r'◇\s*$', '', m)
        parts = m.split('◇')
        cleaned = [p.strip().strip('　') for p in parts if p.strip()]
        m = '＋'.join(cleaned) if cleaned else ''
        m = re.sub(r'\s+', ' ', m).strip()
        if has_off_shampoo and m:
            m = f'{m}（オフあり+アイシャンプー）'
        return m
    
    for b in bookings:
        b['menu'] = clean_menu(b.get('menu', ''))
    
    return jsonify({'bookings': bookings})

@app.route('/api/liff/change-request', methods=['POST'])
def api_liff_change_request():
    """日時変更リクエスト"""
    data = request.get_json()
    booking_id = data.get('booking_id')
    line_user_id = data.get('line_user_id')
    
    print(f"[変更リクエスト] booking_id={booking_id}, line_user_id={line_user_id}")
    
    return jsonify({'success': True, 'message': '変更リクエストを受け付けました。サロンからご連絡いたします。'})

@app.route('/api/liff/cancel-request', methods=['POST'])
def api_liff_cancel_request():
    """キャンセルリクエスト"""
    data = request.get_json()
    booking_id = data.get('booking_id')
    line_user_id = data.get('line_user_id')
    
    print(f"[キャンセルリクエスト] booking_id={booking_id}, line_user_id={line_user_id}")
    
    return jsonify({'success': True, 'message': 'キャンセルリクエストを受け付けました。サロンからご連絡いたします。'})

@app.route("/api/liff/get-duration", methods=["POST"])
def api_liff_get_duration():
    """SalonBoardから予約の所要時間を取得"""
    from playwright.sync_api import sync_playwright
    
    data = request.get_json()
    booking_id = data.get("booking_id")
    
    if not booking_id:
        return jsonify({"error": "booking_id required"}), 400
    
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context()
            cookie_file = os.path.join(os.path.dirname(__file__), "session_cookies.json")
            cookies = None
            if os.path.exists(cookie_file):
                with open(cookie_file, "r") as f:
                    cookies = json.load(f)
            if cookies:
                context.add_cookies(cookies)
            page = context.new_page()
            url = f"https://salonboard.com/KLP/reserve/ext/extReserveChange/?reserveId={booking_id}"
            page.goto(url, timeout=60000)
            page.wait_for_timeout(3000)
            hour_select = page.query_selector("#jsiRsvTermHour")
            min_select = page.query_selector("#jsiRsvTermMin")
            duration = 60
            if hour_select and min_select:
                hour_val = hour_select.evaluate("el => el.value")
                min_val = min_select.evaluate("el => el.value")
                duration = int(hour_val) + int(min_val)
            browser.close()
            return jsonify({"duration": duration})
    except Exception as e:
        return jsonify({"error": str(e), "duration": 60}), 200

@app.route('/api/liff/execute-change', methods=['POST'])
def api_liff_execute_change():
    """予約日時を自動変更"""
    from playwright.sync_api import sync_playwright
    import re
    
    data = request.get_json()
    booking_id = data.get('booking_id')
    new_date = data.get('new_date')  # YYYYMMDD
    new_time = data.get('new_time')  # HH:MM
    line_user_id = data.get('line_user_id')
    
    if not all([booking_id, new_date, new_time]):
        return jsonify({'error': 'booking_id, new_date, new_time required'}), 400
    
    try:
        # 予約IDからSalonBoard用IDを取得
        supabase_url = os.getenv('SUPABASE_URL')
        supabase_key = os.getenv('SUPABASE_KEY')
        headers = {'apikey': supabase_key, 'Authorization': f'Bearer {supabase_key}'}
        
        # 8weeks_bookingsから予約情報取得
        res = requests.get(
            f'{supabase_url}/rest/v1/8weeks_bookings?booking_id=eq.{booking_id}',
            headers=headers
        )
        bookings = res.json()
        if not bookings:
            return jsonify({'error': 'Booking not found'}), 404
        
        booking = bookings[0]
        old_datetime = booking.get('date_time', '')
        customer_name = booking.get('customer_name', '')
        
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context()
            
            with open('session_cookies.json', 'r') as f:
                cookies = json.load(f)
                context.add_cookies(cookies)
            
            page = context.new_page()
            url = f'https://salonboard.com/KLP/reserve/ext/extReserveChange/?reserveId={booking_id}'
            page.goto(url, timeout=60000)
            page.wait_for_timeout(5000)
            
            # 1. 日付変更
            current_date = page.query_selector('input[name="rsvDate"]').get_attribute('value')
            if current_date != new_date:
                cal_input = page.query_selector('.calendar_readonly')
                if cal_input:
                    cal_input.click()
                    page.wait_for_timeout(1000)
                    
                    target_day = new_date[-2:]  # 日だけ取得
                    if target_day.startswith('0'):
                        target_day = target_day[1:]
                    
                    calendar = page.query_selector('.mod_popup_02.js_calendar')
                    if calendar:
                        tds = calendar.query_selector_all('td')
                        for td in tds:
                            if td.is_visible() and td.inner_text().strip() == target_day:
                                td.click()
                                page.wait_for_timeout(1000)
                                break
            
            # 2. 時間変更
            hour, minute = new_time.split(':')
            page.select_option('#rsvHour', hour)
            page.select_option('#rsvMinute', minute)
            page.wait_for_timeout(500)
            
            # 3. 確定ボタンクリック
            confirm_btn = page.query_selector('button:has-text("確定する"), a:has-text("確定する")')
            if confirm_btn:
                confirm_btn.click()
                page.wait_for_timeout(3000)
            
            browser.close()
        
        # 新しい日時文字列
        new_datetime = f'{new_date[:4]}/{new_date[4:6]}/{new_date[6:]} {new_time}'
        
        # 店舗に通知
        notify_shop_booking_change(customer_name, old_datetime, new_datetime)
        
        return jsonify({'success': True, 'message': f'予約を{new_datetime}に変更しました'})
        
    except Exception as e:
        print(f'[予約変更エラー] {e}')
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


# === 空き枠取得API ===
@app.route('/api/liff/available-slots-range', methods=['GET'])
def api_liff_available_slots_range():
    """14日分の空き枠をSupabaseから取得（高速）"""
    from datetime import datetime, timedelta
    
    try:
        supabase_url = os.getenv('SUPABASE_URL')
        supabase_key = os.getenv('SUPABASE_KEY')
        headers = {'apikey': supabase_key, 'Authorization': f'Bearer {supabase_key}'}
        
        today = datetime.now()
        dates = [(today + timedelta(days=i)).strftime('%Y%m%d') for i in range(14)]
        
        date_filter = ','.join(dates)
        res = requests.get(
            f'{supabase_url}/rest/v1/available_slots?date=in.({date_filter})',
            headers=headers
        )
        
        if res.status_code != 200:
            return jsonify({'error': 'Database error'}), 500
        
        rows = res.json()
        
        all_data = {}
        for date_str in dates:
            day_rows = [r for r in rows if r['date'] == date_str]
            staff_schedules = []
            for r in day_rows:
                staff_schedules.append({
                    'staff_id': r['staff_id'],
                    'staff_name': r['staff_name'],
                    'is_day_off': r['is_day_off'],
                    'available_slots': r['slots'] or []
                })
            all_data[date_str] = {'staff_schedules': staff_schedules}
        
        return jsonify({'dates': all_data})
        
    except Exception as e:
        print(f'[空き枠取得エラー] {e}')
        return jsonify({'error': str(e)}), 500

@app.route('/api/liff/available-slots', methods=['GET'])
def api_liff_available_slots():
    """指定日のスタッフ空き枠を取得"""
    from playwright.sync_api import sync_playwright
    import re
    
    date_str = request.args.get('date')  # YYYYMMDD形式
    
    if not date_str:
        return jsonify({'error': 'date parameter required'}), 400
    
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context()
            
            # Supabaseからクッキー取得を試みる
            page = context.new_page()
            cookies_loaded = False
            
            try:
                supabase_url = os.getenv('SUPABASE_URL')
                supabase_key = os.getenv('SUPABASE_KEY')
                if supabase_url and supabase_key:
                    headers = {'apikey': supabase_key, 'Authorization': f'Bearer {supabase_key}'}
                    res = requests.get(f'{supabase_url}/rest/v1/system_settings?key=eq.salonboard_cookies', headers=headers)
                    if res.status_code == 200 and res.json():
                        cookies = json.loads(res.json()[0]['value'])
                        context.add_cookies(cookies)
                        cookies_loaded = True
            except Exception as e:
                print(f'[空き枠] クッキー読み込みエラー: {e}')
            
            # ローカルファイルからも試す
            if not cookies_loaded:
                try:
                    with open('session_cookies.json', 'r') as f:
                        cookies = json.load(f)
                        context.add_cookies(cookies)
                        cookies_loaded = True
                except:
                    pass
            
            url = f'https://salonboard.com/KLP/schedule/salonSchedule/?date={date_str}'
            page.goto(url, timeout=60000)
            page.wait_for_timeout(3000)
            
            # ログインが必要な場合
            if 'login' in page.url.lower():
                print('[空き枠] ログイン実行中...')
                login_id = os.environ.get('SALONBOARD_LOGIN_ID', 'CD18317')
                login_password = os.environ.get('SALONBOARD_LOGIN_PASSWORD', 'Ne8T2Hhi!')
                
                page.goto('https://salonboard.com/login/', timeout=60000)
                page.wait_for_timeout(2000)
                page.fill('input[name="userId"]', login_id)
                page.fill('input[name="password"]', login_password)
                page.evaluate("dologin(new Event('click'))")
                page.wait_for_timeout(5000)
                
                if 'login' in page.url.lower():
                    browser.close()
                    return jsonify({'error': 'Login failed'}), 401
                
                # 再度スケジュールページへ
                page.goto(url, timeout=60000)
            
            page.wait_for_selector(".scheduleMainTableLine", timeout=30000)
            page.wait_for_timeout(2000)
            
            if 'login' in page.url.lower() or 'エラー' in page.content():
                browser.close()
                return jsonify({'error': 'Login required'}), 401
            
            staff_list = []
            staff_options = page.query_selector_all('#stockNameList option')
            for opt in staff_options:
                value = opt.get_attribute('value') or ''
                name = opt.inner_text()
                if value.startswith('STAFF_'):
                    staff_list.append({'id': value.split('_')[1], 'name': name})
            
            PX_PER_HOUR = 132
            START_HOUR = 9
            staff_schedules = []
            staff_rows = page.query_selector_all('.scheduleMainTableLine.jscScheduleMainTableLine')
            
            for i, row in enumerate(staff_rows):
                if i >= len(staff_list):
                    break
                staff_info = staff_list[i]
                booked_slots = []
                # 受付開始時間を取得
                time_list = row.query_selector_all('.scheduleTime')
                start_time = 9  # デフォルト
                if time_list:
                    first_time = time_list[0].inner_text()
                    start_time = int(first_time.split(':')[0])
                
                # 予約の時間帯を取得（scheduleTimeZoneSettingから）
                reservations = row.query_selector_all('.scheduleReservation, .scheduleToDo')
                for res in reservations:
                    time_zone = res.query_selector('.scheduleTimeZoneSetting')
                    if time_zone:
                        time_text = time_zone.inner_text()
                        times = json.loads(time_text)
                        if len(times) >= 2:
                            start_parts = times[0].split(':')
                            end_parts = times[1].split(':')
                            start_h = int(start_parts[0]) + int(start_parts[1]) / 60
                            end_h = int(end_parts[0]) + int(end_parts[1]) / 60
                            booked_slots.append({'start': start_h, 'end': end_h})
                
                day_off = row.query_selector('.isDayOff')
                is_day_off = day_off is not None
                available_slots = []
                if not is_day_off:
                    booked_slots.sort(key=lambda x: x['start'])
                    current = start_time
                    for slot in booked_slots:
                        if slot['start'] > current:
                            import math
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
                        import math
                        current_min = current * 60
                        current_min_rounded = math.ceil(current_min / 10) * 10
                        start_str = f"{int(current_min_rounded // 60)}:{int(current_min_rounded % 60):02d}"
                        available_slots.append({'start': start_str, 'end': '19:00'})
                
                staff_schedules.append({
                    'staff_id': staff_info['id'],
                    'staff_name': staff_info['name'],
                    'is_day_off': is_day_off,
                    'available_slots': available_slots
                })
            
            browser.close()
            return jsonify({'date': date_str, 'staff_schedules': staff_schedules})
    except Exception as e:
        print(f'[空き枠取得エラー] {e}')
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


# APScheduler: 毎分スクレイピング実行
def run_scrape_job():
    """毎分実行されるスクレイピングジョブ"""
    try:
        import requests as req
        print(f"[SCHEDULER] スクレイピング開始: {datetime.now()}", flush=True)
        res = req.post('http://localhost:10000/api/scrape_8weeks_v3', timeout=30)
        print(f"[SCHEDULER] スクレイピング結果: {res.status_code}", flush=True)
    except Exception as e:
        print(f"[SCHEDULER] エラー: {e}", flush=True)

# APScheduler一時停止（ログイン失敗調査中）
scheduler = BackgroundScheduler(timezone='UTC')
scheduler.add_job(run_scrape_job, 'interval', minutes=1, id='scrape_8weeks', next_run_time=datetime.now() + timedelta(seconds=60))
scheduler.start()
print("[SCHEDULER] APScheduler開始（毎分実行）", flush=True)
