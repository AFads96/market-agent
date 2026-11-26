"""Cari TELEGRAM_CHAT_ID Anda.
1) Kirim pesan apa saja ke bot Anda di Telegram.
2) Jalankan:  TELEGRAM_BOT_TOKEN=xxx python get_chat_id.py
"""
import os

import requests

token = os.environ["TELEGRAM_BOT_TOKEN"]
r = requests.get(f"https://api.telegram.org/bot{token}/getUpdates", timeout=20).json()
chats = {}
for u in r.get("result", []):
    m = u.get("message") or u.get("channel_post") or {}
    c = m.get("chat")
    if c:
        chats[c["id"]] = c.get("title") or c.get("username") or c.get("first_name")
if not chats:
    print("Belum ada pesan. Kirim pesan ke bot Anda dulu, lalu jalankan lagi.")
for cid, name in chats.items():
    print(f"TELEGRAM_CHAT_ID={cid}   ({name})")
