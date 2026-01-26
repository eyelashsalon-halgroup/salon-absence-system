# リマインド送信 トラブルシューティング

## 【最短解決】エラー別対処法

### `送信: 401` → LINE変数名間違い
```bash
grep "^LINE_CHANNEL_ACCESS_TOKEN=" .env
# LINE_BOT_TOKEN ではなく LINE_CHANNEL_ACCESS_TOKEN を使う
```

### `KeyError: 0` → 環境変数未読み込み
```bash
cd ~/salon-absence-system && source .env
echo "${SUPABASE_KEY:0:20}"  # 値が出ればOK
```

### `500 Internal Server Error` → 変数未定義
```bash
# 確認
grep -n "staff = booking.get" auth_notification_system.py
grep -n "staff_line = " auth_notification_system.py
# 空なら追加が必要（2865行目と2932行目付近）
```

### `sent: 0` → 送信済みログ削除
```bash
cd ~/salon-absence-system && source .env
curl -X DELETE "$SUPABASE_URL/rest/v1/reminder_logs?phone=eq.09015992055&sent_at=gte.$(date +%Y-%m-%d)T00:00:00" \
  -H "apikey: $SUPABASE_KEY" -H "Authorization: Bearer $SUPABASE_KEY"
```

### 改行消える / Port 5000使用中 → Railway経由でテスト
```bash
curl -s "https://salon-absence-system-production.up.railway.app/api/reminder_test" | jq
```

---

## テスト送信（コピペ）
```bash
cd ~/salon-absence-system && source .env
curl -X DELETE "$SUPABASE_URL/rest/v1/reminder_logs?phone=eq.09015992055&sent_at=gte.$(date +%Y-%m-%d)T00:00:00" -H "apikey: $SUPABASE_KEY" -H "Authorization: Bearer $SUPABASE_KEY"
curl -s "https://salon-absence-system-production.up.railway.app/api/reminder_test" | jq
```

## 送信対象確認（コピペ）
```bash
cd ~/salon-absence-system && source .env
D3=$(date -v+3d +%Y-%m-%d); D7=$(date -v+7d +%Y-%m-%d)
echo "3日後:$D3 / 7日後:$D7"
curl -s "$SUPABASE_URL/rest/v1/8weeks_bookings?visit_datetime=like.${D3}*&select=customer_name,phone" -H "apikey: $SUPABASE_KEY" | jq -r '.[] | "\(.customer_name)|\(.phone)"'
curl -s "$SUPABASE_URL/rest/v1/8weeks_bookings?visit_datetime=like.${D7}*&select=customer_name,phone" -H "apikey: $SUPABASE_KEY" | jq -r '.[] | "\(.customer_name)|\(.phone)"'
```

## 変数名
- `SUPABASE_KEY` / `SUPABASE_URL`
- `LINE_CHANNEL_ACCESS_TOKEN`（顧客）
- `LINE_CHANNEL_ACCESS_TOKEN_STAFF`（スタッフ）
