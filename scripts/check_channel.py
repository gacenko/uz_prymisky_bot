"""
Читає нові пости з публічного каналу @UZprymisky (userbot через Telethon),
фільтрує затримки/скасування/відновлення руху і шле стислі сповіщення
через звичайного Telegram-бота у сімейний чат.

Запускається періодично (див. .github/workflows/check.yml). Стан (id останнього
обробленого повідомлення) зберігається у state/last_message_id.txt і коміститься
назад у репозиторій воркфлоу.
"""

import os
import re

import requests
from telethon.sync import TelegramClient
from telethon.sessions import StringSession

API_ID = int(os.environ["TG_API_ID"])
API_HASH = os.environ["TG_API_HASH"]
SESSION = os.environ["TG_SESSION"]
BOT_TOKEN = os.environ["TG_BOT_TOKEN"]
CHAT_ID = os.environ["TG_CHAT_ID"]
SOURCE_CHANNEL = os.environ.get("SOURCE_CHANNEL", "UZprymisky")

STATE_FILE = os.path.join(os.path.dirname(__file__), "..", "state", "last_message_id.txt")

# Пости, що містять хоч один з цих коренів слів — пересилаємо.
# Решту (новини, реклама, оголошення про майбутнє корегування розкладу тощо) — ігноруємо.
KEYWORDS = [
    "затримк",   # затримка/затримується
    "скасов",    # скасовано/скасування
    "відмін",    # відмінено (синонім скасування)
    "відновл",   # відновлено рух
    "продовж",   # продовжуємо рух
]

DELAY_RE = re.compile(
    r"Поїзд\s*№\s*(?P<num>[\d/]+)\s+(?P<route>.+?)\s+курсує зі станції\s+"
    r"(?P<station>.+?)\s+із затримкою\s+(?P<mins>\d+)\s*хв",
    re.IGNORECASE | re.DOTALL,
)

# Типовий "аварійний" футер, що повторюється майже в кожному пості й не потрібен у сімейному чаті.
BOILERPLATE_RE = re.compile(
    r"❗️?\s*У разі підвищеної небезпеки.*", re.IGNORECASE | re.DOTALL
)


def classify(text: str) -> str | None:
    lowered = text.lower()
    if not any(kw in lowered for kw in KEYWORDS):
        return None
    if "скасов" in lowered or "відмін" in lowered:
        return "cancel"
    if "затримк" in lowered:
        return "delay"
    if "відновл" in lowered or "продовж" in lowered:
        return "resume"
    return "other"


def format_message(text: str, category: str, link: str) -> str:
    match = DELAY_RE.search(text)
    if match:
        num = match.group("num")
        route = match.group("route").strip()
        station = match.group("station").strip()
        mins = match.group("mins")
        body = f"🚆 №{num} {route}\n⏱ Затримка {mins} хв (ст. {station})"
    else:
        cleaned = BOILERPLATE_RE.sub("", text).strip()
        icon = {"delay": "⏱", "cancel": "⛔", "resume": "✅"}.get(category, "🚆")
        body = f"{icon} {cleaned}"

    return f"{body}\n\n{link}"


def read_last_id() -> int:
    if not os.path.exists(STATE_FILE):
        return 0
    with open(STATE_FILE, encoding="utf-8") as f:
        content = f.read().strip()
        return int(content) if content else 0


def write_last_id(msg_id: int) -> None:
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        f.write(str(msg_id))


def send_to_family_chat(text: str) -> None:
    resp = requests.post(
        f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
        json={
            "chat_id": CHAT_ID,
            "text": text,
            "disable_web_page_preview": True,
        },
        timeout=15,
    )
    if not resp.ok:
        print(f"Bot API error {resp.status_code}: {resp.text}")


def main() -> None:
    last_id = read_last_id()
    bootstrap = last_id == 0

    with TelegramClient(StringSession(SESSION), API_ID, API_HASH) as client:
        entity = client.get_entity(SOURCE_CHANNEL)

        if bootstrap:
            latest = client.get_messages(entity, limit=1)
            if latest:
                write_last_id(latest[0].id)
                print(f"Bootstrap: set last_message_id={latest[0].id}, нічого не надсилаю.")
            return

        messages = list(client.iter_messages(entity, min_id=last_id, reverse=True, limit=200))

        max_id = last_id
        for msg in messages:
            max_id = max(max_id, msg.id)
            text = msg.message or ""
            if not text:
                continue

            category = classify(text)
            if category is None:
                continue

            link = f"https://t.me/{SOURCE_CHANNEL}/{msg.id}"
            formatted = format_message(text, category, link)
            send_to_family_chat(formatted)
            print(f"Sent message id={msg.id} category={category}")

        if max_id != last_id:
            write_last_id(max_id)


if __name__ == "__main__":
    main()
