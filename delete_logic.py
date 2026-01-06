# scrape_8weeks_v4.py の「# 成功したのでカウンターリセット」の直前に追加

    # ===== 安全な削除ロジック（厳格版） =====
    if all_bookings:
        fetched_ids = [b["booking_id"] for b in all_bookings if b.get("booking_id")]
        total_fetched = len(fetched_ids)
        error_count = sum(1 for b in all_bookings if not b.get("menu") or not b.get("phone"))
        error_rate = error_count / max(total_fetched, 1)
        print(f"[削除判定] 取得: {total_fetched}件, エラー: {error_count}件 ({error_rate:.1%})", flush=True)
        if total_fetched >= 200 and error_rate < 0.05:
            today_dt = datetime.now()
            eight_weeks_later = today_dt + timedelta(days=56)
            db_res = requests.get(f"{SUPABASE_URL}/rest/v1/8weeks_bookings?select=booking_id,visit_datetime", headers=headers)
            if db_res.status_code == 200:
                delete_candidates = []
                for row in db_res.json():
                    bid = row.get("booking_id")
                    vdt = row.get("visit_datetime", "")[:10]
                    try:
                        visit_dt = datetime.strptime(vdt, "%Y-%m-%d")
                        if today_dt <= visit_dt <= eight_weeks_later and bid and bid not in fetched_ids:
                            delete_candidates.append(bid)
                    except: pass
                if delete_candidates:
                    print(f"[削除実行] {len(delete_candidates)}件: {delete_candidates[:5]}...", flush=True)
                    for bid in delete_candidates:
                        requests.delete(f"{SUPABASE_URL}/rest/v1/8weeks_bookings?booking_id=eq.{bid}", headers=headers)
                    print(f"[削除完了] {len(delete_candidates)}件削除", flush=True)
                else:
                    print("[削除] 対象なし", flush=True)
        else:
            print(f"[削除スキップ] 条件未達（200件以上かつエラー率5%未満が必要）", flush=True)
