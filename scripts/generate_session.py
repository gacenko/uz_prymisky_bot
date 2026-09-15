"""
One-off local script: logs into your personal Telegram account and prints a
TG_SESSION (Telethon string session). Do NOT run this in CI — local only.

Usage:
    python scripts/generate_session.py

Prompts for API_ID / API_HASH (from https://my.telegram.org), then your
phone number, the confirmation code, and (if enabled) your 2FA password.
"""

from telethon.sync import TelegramClient
from telethon.sessions import StringSession

api_id = int(input("API_ID (https://my.telegram.org): ").strip())
api_hash = input("API_HASH: ").strip()

with TelegramClient(StringSession(), api_id, api_hash) as client:
    session_string = client.session.save()
    print("\n=== TG_SESSION (add as a GitHub secret, don't share it) ===\n")
    print(session_string)
    print()
