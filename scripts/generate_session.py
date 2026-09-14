"""
Одноразовий локальний скрипт: логінить твій особистий Telegram-акаунт і друкує
TG_SESSION (string session) для Telethon. НЕ запускати в CI — тільки локально.

Запуск:
    python scripts/generate_session.py

Запитає API_ID / API_HASH (з https://my.telegram.org), потім номер телефону,
код підтвердження і (якщо є) пароль двофакторки.
"""

from telethon.sync import TelegramClient
from telethon.sessions import StringSession

api_id = int(input("API_ID (https://my.telegram.org): ").strip())
api_hash = input("API_HASH: ").strip()

with TelegramClient(StringSession(), api_id, api_hash) as client:
    session_string = client.session.save()
    print("\n=== TG_SESSION (додай як GitHub secret, нікому не показуй) ===\n")
    print(session_string)
    print()
