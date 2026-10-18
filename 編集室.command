#!/bin/bash
# iro:re 作品サイトの編集室を開く（ダブルクリック）。
# 編集室は Mac の起動と同時に裏で動いている（~/Library/LaunchAgents/com.irore.editor.plist）。
# これは、それを立て直して（最新の仕組みを読み込み直して）ブラウザで開くだけ。お気に入りの 127.0.0.1:8490 から開いても同じ。
cd "$(dirname "$0")" || exit 1
git pull --ff-only -q 2>/dev/null
launchctl kickstart -k "gui/$(id -u)/com.irore.editor"
sleep 1
open "http://127.0.0.1:8490/"
