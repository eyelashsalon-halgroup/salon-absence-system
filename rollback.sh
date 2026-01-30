#!/bin/bash
# 緊急ロールバック: 1つ前のコミットに戻してデプロイ
cd ~/salon-absence-system
echo "現在のコミット:"
git log --oneline -1
echo ""
echo "1つ前に戻します..."
git revert --no-commit HEAD
python3 -m py_compile auth_notification_system.py
if [ $? -eq 0 ]; then
    git commit -m "Emergency rollback"
    git push origin main
    echo "✅ ロールバック完了"
else
    git reset --hard HEAD
    echo "❌ 構文エラーのためロールバック中止"
fi
