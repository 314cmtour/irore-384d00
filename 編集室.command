#!/bin/bash
# iro:re 作品サイトの編集室を開く（ダブルクリック）。
# ★編集室は母艦（Mac mini）で常に動いている（2026-10-18〜）。この Mac でも iPhone でも、同じ編集室を Tailscale 経由で開く。
#   母艦の置き場：~/irore-site／常駐：~/Library/LaunchAgents/com.irore.editor.plist（母艦側）
#   開けないときは Tailscale がつながっているか確かめる。
open "http://100.64.108.42:8490/"
