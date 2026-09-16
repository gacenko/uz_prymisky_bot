"""
Reads new posts from the public @UZprymisky channel (userbot via Telethon),
filters delay/cancellation/resume-of-service posts for trains on the Nizhyn -
Kyiv route (Kniazhychi -> Berezniaky section), and forwards a short
notification through a regular Telegram bot to the family chat.

Runs once per `workflow_dispatch` call (see .github/workflows/check.yml),
triggered by a Cloudflare Worker Cron Trigger (worker/) instead of GitHub
Actions' native `schedule:` (which in practice delayed frequent scheduled
runs by hours instead of the configured minutes).

State (id of the last processed message) is kept in
state/last_message_id.txt and committed back to the repo by the workflow
itself.
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

# Suburban train timetable for the Nizhyn - Kyiv direction on the
# Kniazhychi -> Berezniaky section (the family's commute: Brovary -> Kyiv).
# Source: UZ suburban timetable, valid 2026-06-28..2026-12-12. Update here
# when the seasonal timetable changes.
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

# Posts containing at least one of these word roots get forwarded (provided
# they also concern a train from TRAIN_SCHEDULE above). Everything else
# (news, ads, announcements of future timetable changes, etc.) is ignored.
KEYWORDS = [
    "затримк",   # delay(ed)
    "скасов",    # cancelled/cancellation
    "відмін",    # cancelled (synonym)
    "відновл",   # service resumed
    "продовж",   # continuing/resuming
]

# Skip the notification if the recalculated Kniazhychi time is still earlier
# than this — a delay that still clears before 9am isn't worth a heads-up.
CUTOFF_TIME = "09:30"

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

# The standard "emergency" footer repeated in almost every post — not needed in the family chat.
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


def build_delay_blocks(text: str) -> tuple[list[str], bool]:
    """A single post can contain several "Поїзд №... курсує..." sentences at
    once (one per train). Each is processed independently — otherwise we'd
    grab data from the wrong train whenever the first sentence in a post
    isn't about our route.

    Returns (blocks for relevant trains, whether at least one structured
    sentence was found at all — so main() can tell "nothing relevant / all
    cut off by CUTOFF_TIME" apart from "post format wasn't recognized at all").
    """
    matches = list(DELAY_RE.finditer(text))
    blocks = []
    for m in matches:
        train_key = next((n for n in m.group("num").split("/") if n in TRAIN_SCHEDULE), None)
        if not train_key:
            continue

        line1 = m.group("full").strip()
        if not line1.endswith("."):
            line1 += "."
        lines = [f"🚆 {line1}"]

        delay_min = parse_delay_minutes(m.group("delay_text"))
        if delay_min is not None:
            sched = TRAIN_SCHEDULE[train_key]
            new_dep = add_minutes(sched["dep"], delay_min)
            if new_dep < CUTOFF_TIME:
                continue
            new_arr = add_minutes(sched["arr"], delay_min)
            lines.append(f"🕐 Розрахунково: Княжичі відпр. {new_dep} → Березняки приб. {new_arr}")

        blocks.append("\n".join(lines))

    return blocks, bool(matches)


def format_message(text: str, category: str, link: str) -> str:
    cleaned = BOILERPLATE_RE.sub("", text).strip()
    icon = {"delay": "⏱", "cancel": "⛔", "resume": "✅"}.get(category, "🚆")
    return f"{icon} {cleaned}\n\n{link}"


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

            if category == "delay":
                blocks, matched_structured = build_delay_blocks(text)
                if blocks:
                    formatted = "\n\n".join(blocks) + f"\n\n{link}"
                elif not matched_structured and is_relevant(text):
                    # Unusual post format (regex didn't parse it), but our train is
                    # mentioned — better to forward as-is than silently miss it.
                    formatted = format_message(text, category, link)
                else:
                    continue
            else:
                if not is_relevant(text):
                    continue
                formatted = format_message(text, category, link)

            send_to_family_chat(formatted)
            print(f"Sent message id={msg.id} category={category}")

        if max_id != last_id:
            write_last_id(max_id)


if __name__ == "__main__":
    main()
