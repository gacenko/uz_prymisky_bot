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
from datetime import datetime, timedelta

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

# Розклад приміських поїздів напрямку Ніжин – Київ на дільниці Княжичі → Березняки
# (маршрут тещі: Бровари → Київ). Джерело: розклад руху приміських поїздів УЗ,
# чинний 2026-06-28..2026-12-12. При зміні сезонного розкладу — оновити тут.
TRAIN_SCHEDULE = {
    "6903": {"dep": "05:36", "arr": "06:01"},
    "6905": {"dep": "06:03", "arr": "06:29"},
    "6909": {"dep": "07:05", "arr": "07:30"},
    "6911": {"dep": "07:47", "arr": "08:11"},
    "6913": {"dep": "10:14", "arr": "10:40"},
    "6917": {"dep": "12:55", "arr": "13:22"},
    "6923": {"dep": "17:07", "arr": "17:30"},
    "6925": {"dep": "18:49", "arr": "19:13"},
    "6927": {"dep": "22:08", "arr": "22:32"},
}

# Пости, що містять хоч один з цих коренів слів — пересилаємо (за умови що стосуються
# поїзда з TRAIN_SCHEDULE вище). Решту (новини, реклама, оголошення про майбутнє
# корегування розкладу тощо) — ігноруємо.
KEYWORDS = [
    "затримк",   # затримка/затримується
    "скасов",    # скасовано/скасування
    "відмін",    # відмінено (синонім скасування)
    "відновл",   # відновлено рух
    "продовж",   # продовжуємо рух
]

TRAIN_NUM_RE = re.compile(r"№\s*([\d/]+)")

DELAY_RE = re.compile(
    r"(?P<full>Поїзд\s*№\s*(?P<num>[\d/]+)\s+(?P<route>.+?)\s+курсує зі станції\s+"
    r"(?P<station>.+?)\s+із затримкою\s+"
    r"(?P<delay_text>(?:\d+\s*год\.?\s*)?(?:\d+\s*хв\.?)?))",
    re.IGNORECASE | re.DOTALL,
)

DELAY_DURATION_RE = re.compile(
    r"(?:(?P<hours>\d+)\s*год\.?)?\s*(?:(?P<mins>\d+)\s*хв\.?)?", re.IGNORECASE
)

# Типовий "аварійний" футер, що повторюється майже в кожному пості й не потрібен у сімейному чаті.
BOILERPLATE_RE = re.compile(
    r"❗️?\s*У разі підвищеної небезпеки.*", re.IGNORECASE | re.DOTALL
)


def relevant_train_numbers(text: str) -> list[str]:
    nums = []
    for m in TRAIN_NUM_RE.finditer(text):
        nums.extend(m.group(1).split("/"))
    return nums


def is_relevant(text: str) -> bool:
    return any(n in TRAIN_SCHEDULE for n in relevant_train_numbers(text))


def parse_delay_minutes(delay_text: str) -> int | None:
    m = DELAY_DURATION_RE.search(delay_text)
    if not m or not (m.group("hours") or m.group("mins")):
        return None
    hours = int(m.group("hours") or 0)
    mins = int(m.group("mins") or 0)
    return hours * 60 + mins


def add_minutes(hhmm: str, minutes: int) -> str:
    t = datetime.strptime(hhmm, "%H:%M") + timedelta(minutes=minutes)
    return t.strftime("%H:%M")


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
    if match and category == "delay":
        line1 = match.group("full").strip()
        if not line1.endswith("."):
            line1 += "."
        lines = [f"🚆 {line1}"]

        train_key = next((n for n in match.group("num").split("/") if n in TRAIN_SCHEDULE), None)
        if train_key:
            delay_min = parse_delay_minutes(match.group("delay_text"))
            if delay_min is not None:
                sched = TRAIN_SCHEDULE[train_key]
                new_dep = add_minutes(sched["dep"], delay_min)
                new_arr = add_minutes(sched["arr"], delay_min)
                lines.append(f"🕐 Розрахунково: Княжичі відпр. {new_dep} → Березняки приб. {new_arr}")

        body = "\n".join(lines)
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
            if not is_relevant(text):
                continue

            link = f"https://t.me/{SOURCE_CHANNEL}/{msg.id}"
            formatted = format_message(text, category, link)
            send_to_family_chat(formatted)
            print(f"Sent message id={msg.id} category={category}")

        if max_id != last_id:
            write_last_id(max_id)


if __name__ == "__main__":
    main()
