# HAL サロン予約管理システム - 全体概要

## 📅 最終更新: 2026-01-11

---

## 🏗️ システム構成

### デプロイ環境
- **バックエンド**: Railway (https://salon-absence-system-production.up.railway.app)
- **データベース**: Supabase (PostgreSQL)
- **LINE Bot**: LINE Messaging API
- **スクレイピング対象**: SalonBoard

---

## 📁 主要ファイル構成

### バックエンド（メイン）
| ファイル | 役割 | 状態 |
|---------|------|------|
| `auth_notification_system.py` | Flaskメインアプリ（API全て含む） | ✅ 稼働中 |
| `scrape_8weeks_v4.py` | 8週間予約スクレイピング（最新版） | ✅ 稼働中 |
| `cancel_booking.py` | キャンセル検知・LINE通知 | ✅ 稼働中 |

### テンプレート（HTML）
| ファイル | 役割 |
|---------|------|
| `templates/admin.html` | 管理画面 |
| `templates/customers.html` | 顧客一覧 |
| `templates/absences.html` | スタッフ欠勤管理 |
| `templates/staff_absence.html` | スタッフ用欠勤申請 |
| `templates/login.html` | ログイン画面 |
| `templates/scrape.html` | スクレイピング管理 |

### バックアップ・旧版
| ファイル | 説明 |
|---------|------|
| `scrape_8weeks_v4_backup.py` | v4旧方法バックアップ |
| `scrape_8weeks_v4_working_backup.py` | 動作確認済みバックアップ |
| `scrape_8weeks_v3.py` | v3版（参考用） |
| `scrape_8weeks_v2.py` | v2版（参考用） |

---

## 🗄️ データベース（Supabase）

### テーブル一覧
| テーブル | 用途 |
|---------|------|
| `8weeks_bookings` | 8週間分の予約データ |
| `available_slots` | 空き枠データ |
| `customers` | 顧客マスタ（LINE ID含む） |
| `reminder_logs` | リマインド送信履歴 |
| `salon_menus` | サロンメニューマスタ |
| `salonboard_menus` | SalonBoardメニュー同期 |
| `salon_staff` | スタッフマスタ |
| `message_templates` | LINE通知テンプレート |

---

## 🔄 完了済みフロー

### 1. 予約スクレイピング（自動）
```
[毎1分] 高速版（14日） → SalonBoard → DB更新
[毎5分] 通常版（56日） → SalonBoard → DB更新（詳細含む）
```
- **ファイル**: `scrape_8weeks_v4.py`
- **スケジューラー**: `auth_notification_system.py` 内
- **所要時間**: 高速版約20秒、通常版約50秒（Railway）

### 2. キャンセル検知・LINE通知（自動）
```
[毎1分] スクレイピング後 → キャンセル検知 → LINE通知
```
- **ファイル**: `cancel_booking.py`
- **通知先**: 神原良祐、神原茉衣、test沙織
- **完成機能**:
  - ✅ キャンセル優先スキップ
  - ✅ リトライ30秒後
  - ✅ 予約番号マッチング

### 3. リマインド通知（自動）
```
[毎朝9:00 JST] 前日リマインド → LINE送信
```
- **対象**: 神原良祐、test沙織のみ
- **ファイル**: `auth_notification_system.py` 内

### 4. LIFF予約確認画面
```
顧客 → LINEリッチメニュー → LIFF → 予約確認/変更/キャンセル
```
- **URL**: `/liff/booking`
- **機能**:
  - ✅ 予約確認表示
  - ✅ メニュー表示（修正済み：過去メニュー混入防止）
  - ✅ 日時変更リンク
  - ✅ キャンセルリンク

### 5. 管理画面
```
スタッフ → /admin → 予約一覧/顧客管理/設定
```
- **認証**: Googleログイン

---

## 🚧 未完了・改善予定

### 1. メニュー金額同期（毎晩21時）
- **状態**: 未実装
- **予定**: SalonBoardメニュー → DB同期

### 2. 空き枠変更通知
- **状態**: 未実装
- **予定**: 空き枠増加時に顧客へ通知

### 3. 顧客LINE ID自動紐付け
- **状態**: 手動紐付け
- **改善**: 初回予約時に自動マッチング

---

## 📡 API エンドポイント一覧

### 予約関連
| エンドポイント | メソッド | 説明 |
|---------------|---------|------|
| `/api/scrape_8weeks_v4` | GET/POST | 8週間スクレイピング実行 |
| `/api/scrape_8weeks_v4?days_limit=14` | GET/POST | 高速版（14日） |
| `/api/cancel-detection` | POST | キャンセル検知実行 |
| `/api/bookings` | GET | 予約一覧取得 |

### LIFF関連
| エンドポイント | メソッド | 説明 |
|---------------|---------|------|
| `/liff/booking` | GET | 予約確認画面 |
| `/liff/reschedule` | GET | 日時変更画面 |
| `/liff/cancel` | POST | キャンセル処理 |

### 管理関連
| エンドポイント | メソッド | 説明 |
|---------------|---------|------|
| `/admin` | GET | 管理画面 |
| `/api/customers` | GET | 顧客一覧 |
| `/api/staff` | GET | スタッフ一覧 |

---

## 🔧 環境変数（Railway）
```
SUPABASE_URL=https://xxx.supabase.co
SUPABASE_KEY=xxx
LINE_CHANNEL_ACCESS_TOKEN=xxx
LINE_CHANNEL_SECRET=xxx
LIFF_ID=xxx
SALONBOARD_LOGIN_ID=CD18317
SALONBOARD_LOGIN_PASSWORD=xxx
GOOGLE_CLIENT_ID=xxx
GOOGLE_CLIENT_SECRET=xxx
SECRET_KEY=xxx
```

---

## 📊 パフォーマンス実測値（Railway）

| 処理 | 所要時間 |
|------|----------|
| 高速版スクレイピング（14日） | 17〜20秒 |
| 通常版スクレイピング（56日） | 46〜50秒 |
| キャンセル検知 | 数秒 |

---

## 🐛 解決済みの主要問題

1. **メニュー過去履歴混入** (2026-01-11)
   - 原因: ページ全体からメニューパターン抽出
   - 解決: メニュー行のみから取得に変更

2. **ログインボタンセレクタ** (2026-01-10)
   - 原因: SalonBoardのUI変更
   - 解決: 複数パターン対応

3. **Phase2タイムアウト** (2026-01-10)
   - 原因: 別ブラウザ起動でログイン必要
   - 解決: ワーカー内で詳細取得に変更

---

## 📝 重要な設定値

### スクレイピング待機時間（最適値）
```python
page.wait_for_timeout(1000)  # ページ遷移後
page.wait_for_timeout(500)   # 要素待ち
page.wait_for_timeout(300)   # 軽い待機
page.wait_for_timeout(150)   # 最小待機
```

### 並列ワーカー数
```python
workers = 6  # 8は効果なし
```

---

## 🔗 関連リポジトリ・リンク

- GitHub: https://github.com/ryosukekambara/salon-absence-system
- Railway: https://railway.app
- Supabase: https://supabase.com/dashboard
- LINE Developers: https://developers.line.biz

