#!/bin/bash
# iro:re 作品サイトの編集室を開く（ダブルクリック）。このウィンドウを閉じると編集室も閉じる。
cd "$(dirname "$0")" || exit 1
git pull --ff-only -q 2>/dev/null
exec python3 _editor/server.py
