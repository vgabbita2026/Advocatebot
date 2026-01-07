# interactive_bot_final.py
# WhatsApp Web Bot (Text + Telugu Audio Attachment) + Scheduled Reminders + Admin Audio Toggle via SQLite
#
# ✅ Reliable: sends AUDIO as ATTACHMENT (MP3) — not “voice note”
# ✅ Telugu TTS (gTTS lang="te") with pronunciation-friendly phrasing
# ✅ Uses SQLite settings table: settings(key,value) where audio_enabled = true/false
# ✅ Scheduled reminders: today / tomorrow / day-after (0/1/2 days) – configurable
#
# ---------------------------------------------------------
# INSTALL (inside venv)
#   pip install selenium webdriver-manager gTTS
#
# RUN
#   python interactive_bot_final.py
#
# DB REQUIREMENTS
# Table: cases(client_name, phone, case_id, hearing_date, hearing_time)
#   hearing_date must be ISO format: YYYY-MM-DD
# Table: settings(key TEXT PRIMARY KEY, value TEXT)
#   row: ('audio_enabled', 'true')  -- toggle from your admin UI (myapp.py)
# ---------------------------------------------------------

import os
import re
import time
import uuid
import sqlite3
import datetime
from typing import Optional, List, Tuple

from gtts import gTTS

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from webdriver_manager.chrome import ChromeDriverManager


DB_FILE = "cases.db"

# Chrome path (adjust if needed)
CHROME_BINARY = r"C:\Program Files\Google\Chrome\Application\chrome.exe"

# WhatsApp login wait
QR_WAIT_SECONDS = 20

# Poll interval for incoming messages
POLL_SECONDS = 1.2

# Scheduled reminders check interval
REMINDER_POLL_SECONDS = 30

# Which reminders to send (days before hearing)
REMINDER_DAYS = [2, 1, 0]

# If you only want audio for certain commands, set True and keep keywords below.
# If False, audio will be sent for every bot reply (not recommended).
AUDIO_ONLY_FOR_KEYWORDS = True

VOICE_KEYWORDS = [
    "case",         # case 12345
    "history",      # case history / full history
    "hearing",      # next hearing
    "next hearing",
    "all hearings",
    "full history",
    "case history",
    "hearing history",
]


# ==========================================================
#                    DB / SETTINGS
# ==========================================================
def db_conn():
    return sqlite3.connect(DB_FILE)


def ensure_settings_table():
    conn = db_conn()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)
    cur.execute("""
        INSERT OR IGNORE INTO settings(key, value)
        VALUES ('audio_enabled', 'true')
    """)
    conn.commit()
    conn.close()


def is_audio_enabled() -> bool:
    """
    Admin toggle comes from DB:
    settings(key='audio_enabled', value='true' or 'false')
    """
    try:
        conn = db_conn()
        cur = conn.cursor()
        cur.execute("SELECT value FROM settings WHERE key='audio_enabled'")
        row = cur.fetchone()
        conn.close()
        return (row is not None) and (row[0].strip().lower() == "true")
    except Exception:
        return True  # safe default


# ==========================================================
#                 PHONE NORMALIZATION
# ==========================================================
def normalize_phone(sender_phone: Optional[str]) -> Optional[str]:
    """
    Match sender to DB phone using LAST 10 digits (India-friendly).
    WhatsApp data-id contains something like: false_919640733498@c.us_...
    DB might store +919640733498 or +91xxxxxxxxxx.
    """
    if not sender_phone:
        return None

    sender_digits = re.sub(r"\D", "", sender_phone)
    if len(sender_digits) < 10:
        return None
    sender_last10 = sender_digits[-10:]

    conn = db_conn()
    cur = conn.cursor()
    cur.execute("SELECT DISTINCT phone FROM cases")
    db_phones = [r[0] for r in cur.fetchall()]
    conn.close()

    for db_phone in db_phones:
        db_digits = re.sub(r"\D", "", str(db_phone))
        if len(db_digits) >= 10 and db_digits[-10:] == sender_last10:
            return str(db_phone).strip()

    return None


def phone_to_whatsapp_send_number(db_phone: str) -> str:
    """
    WhatsApp send URL expects countrycode+number digits without '+'
    Example: +919640733498 -> 919640733498
    """
    digits = re.sub(r"\D", "", db_phone)
    return digits


# ==========================================================
#                 TELUGU PRONUNCIATION
# ==========================================================
TELUGU_MONTHS = {
    1: "జనవరి", 2: "ఫిబ్రవరి", 3: "మార్చి", 4: "ఏప్రిల్",
    5: "మే", 6: "జూన్", 7: "జూలై", 8: "ఆగస్టు",
    9: "సెప్టెంబర్", 10: "అక్టోబర్", 11: "నవెంబర్", 12: "డిసెంబర్"
}


def format_date_telugu(iso_date: str) -> str:
    """
    YYYY-MM-DD -> '17 డిసెంబర్ 2025'
    """
    try:
        d = datetime.date.fromisoformat(iso_date.strip())
        return f"{d.day} {TELUGU_MONTHS.get(d.month, str(d.month))} {d.year}"
    except Exception:
        return iso_date


def to_telugu(reply_text: str) -> str:
    """
    Convert English bot reply into Telugu-friendly speech text.
    Keep it simple but clear.
    """
    # Normalize lines
    text = reply_text.replace("\r", "").strip()

    # Key phrase translations
    text = text.replace("Your next hearing:", "మీ తదుపరి విచారణ వివరాలు:")
    text = text.replace("Next hearing is:", "తదుపరి విచారణ వివరాలు:")
    text = text.replace("You have no upcoming hearings.", "మీకు ముందున్న విచారణలు లేవు.")
    text = text.replace("No hearings scheduled for you.", "మీకు షెడ్యూల్ చేసిన విచారణలు లేవు.")
    text = text.replace("No hearing history found.", "మీ విచారణ చరిత్రలో వివరాలు లభించలేదు.")
    text = text.replace("Case Hearing History:", "మీ కేసుల విచారణ చరిత్ర:")
    text = text.replace("Case", "కేసు నంబర్")
    text = text.replace("Client:", "క్లయింట్:")
    text = text.replace("Date:", "తేదీ:")
    text = text.replace("Next hearing:", "తదుపరి విచారణ:")
    text = text.replace("Hearings:", "విచారణలు:")

    # Make " at " sound better (time)
    text = text.replace(" at ", " సమయం ")

    # Convert any ISO dates in text to Telugu format
    # Find patterns like 2025-12-29
    for m in set(re.findall(r"\b\d{4}-\d{2}-\d{2}\b", text)):
        text = text.replace(m, format_date_telugu(m))

    return text


# ==========================================================
#                 AUDIO GENERATION (MP3)
# ==========================================================
def text_to_audio_mp3(telugu_text: str) -> str:
    """
    Generates MP3 using gTTS Telugu and returns absolute file path.
    """
    uid = uuid.uuid4().hex
    mp3_file = f"audio_{uid}.mp3"
    tts = gTTS(text=telugu_text, lang="te", slow=False)
    tts.save(mp3_file)
    return os.path.abspath(mp3_file)


# ==========================================================
#                 BOT SEARCH LOGIC (SQLite)
# ==========================================================
def search_case(query_text: str, sender_phone: Optional[str]) -> str:
    """
    Commands supported:
      - "case 12345" / "12345"  -> all hearings for case_id
      - "next hearing" / "hearing" -> next upcoming hearing for THIS sender phone
      - "history" / "case history" / "all hearings" -> all hearing history for THIS sender phone
    """
    query_text = (query_text or "").lower().strip()

    # Normalize sender phone -> DB phone
    db_phone = normalize_phone(sender_phone)
    if not db_phone:
        return "Your number is not registered in the system."

    conn = db_conn()
    cur = conn.cursor()

    # Extract case ID if present
    m = re.search(r"\b(\d{3,10})\b", query_text)
    case_id = m.group(1) if m else None

    # 1) HISTORY (for this phone)
    if any(k in query_text for k in ["history", "all hearings", "hearing history", "case history", "full history"]):
        cur.execute("""
            SELECT case_id, hearing_date, hearing_time
            FROM cases
            WHERE phone = ?
            ORDER BY hearing_date ASC
        """, (db_phone,))
        rows = cur.fetchall()
        conn.close()

        if not rows:
            return "No hearing history found."

        out = ["Your Case Hearing History:"]
        for cid, d, t in rows:
            out.append(f"Case {cid}: {str(d).strip()} at {str(t).strip()}")
        return "\n".join(out)

    # 2) NEXT HEARING (for this phone)
    if ("next hearing" in query_text) or (query_text == "hearing") or (query_text.endswith("hearing")):
        cur.execute("""
            SELECT case_id, hearing_date, hearing_time
            FROM cases
            WHERE phone = ?
        """, (db_phone,))
        rows = cur.fetchall()
        conn.close()

        if not rows:
            return "No hearings scheduled for you."

        today = datetime.date.today()
        upcoming: List[Tuple[datetime.date, str, str]] = []

        for cid, d, t in rows:
            try:
                dd = datetime.date.fromisoformat(str(d).strip())
                if dd >= today:
                    upcoming.append((dd, str(cid).strip(), str(t).strip()))
            except Exception:
                pass

        if not upcoming:
            return "You have no upcoming hearings."

        upcoming.sort(key=lambda x: x[0])
        dd, cid, tt = upcoming[0]
        return f"Your next hearing:\nCase {cid}\nDate: {dd.isoformat()} at {tt}"

    # 3) CASE LOOKUP (all hearings for case_id, not restricted by phone)
    if case_id:
        cur.execute("""
            SELECT client_name, hearing_date, hearing_time
            FROM cases
            WHERE case_id = ?
            ORDER BY hearing_date ASC
        """, (case_id,))
        rows = cur.fetchall()
        conn.close()

        if not rows:
            return "Case not found."

        name = str(rows[0][0]).strip()
        out = [f"Case {case_id} Hearings:", f"Client: {name}"]
        for _, d, t in rows:
            out.append(f"- {str(d).strip()} at {str(t).strip()}")
        return "\n".join(out)

    conn.close()
    return "I didn't understand. Try: 'next hearing', 'case history', or 'case 12345'."


# ==========================================================
#                 SELENIUM HELPERS
# ==========================================================
def build_driver() -> webdriver.Chrome:
    options = Options()
    options.add_argument("--disable-infobars")
    options.add_argument("--start-maximized")
    options.binary_location = CHROME_BINARY
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
    return driver


def wait_for_whatsapp_ready(driver: webdriver.Chrome, timeout: int = 120):
    """
    Wait until WhatsApp Web is loaded and the message box is available.
    """
    WebDriverWait(driver, timeout).until(
        EC.presence_of_element_located((By.XPATH, "//div[@contenteditable='true' and @role='textbox']"))
    )


def get_input_box(driver: webdriver.Chrome, timeout: int = 30):
    return WebDriverWait(driver, timeout).until(
        EC.presence_of_element_located((By.XPATH, "//div[@contenteditable='true' and @role='textbox']"))
    )


def safe_send_text(driver: webdriver.Chrome, text: str):
    """
    Avoid click-intercept issues by focusing via JS and using send_keys.
    """
    box = get_input_box(driver)
    driver.execute_script("arguments[0].focus();", box)
    time.sleep(0.05)
    box.send_keys(text)
    box.send_keys(Keys.ENTER)


def send_audio_attachment(driver: webdriver.Chrome, audio_path: str, timeout: int = 30):
    """
    Reliable approach: send AUDIO as file attachment (MP3).
    """
    # Attach button
    attach = WebDriverWait(driver, timeout).until(
        EC.element_to_be_clickable((By.XPATH, "//button[contains(@aria-label,'Attach')]"))
    )
    attach.click()
    time.sleep(0.4)

    # File input
    file_input = WebDriverWait(driver, timeout).until(
        EC.presence_of_element_located((By.XPATH, "//input[@type='file']"))
    )
    file_input.send_keys(audio_path)
    time.sleep(1.5)

    # Send button for attachment preview (works reliably for files)
    send_btn = WebDriverWait(driver, timeout).until(
        EC.element_to_be_clickable((By.XPATH, "//button[contains(@aria-label,'Send')]"))
    )
    driver.execute_script("arguments[0].click();", send_btn)
    time.sleep(0.6)


def should_send_audio_for_message(msg_text: str) -> bool:
    if not AUDIO_ONLY_FOR_KEYWORDS:
        return True
    lt = (msg_text or "").lower()
    return any(k in lt for k in VOICE_KEYWORDS)


def extract_sender_phone_from_data_id(data_id: str) -> Optional[str]:
    """
    data-id example: false_919640733498@c.us_AC...
    """
    if not data_id:
        return None
    m = re.search(r"false_(\d+)@c\.us", data_id)
    if m:
        return "+" + m.group(1)
    return None


# ==========================================================
#                 SCHEDULED REMINDERS
# ==========================================================
def build_telugu_reminder(case_id: str, hearing_date_iso: str, hearing_time: str, days_before: int) -> str:
    """
    Telugu reminder message text for TTS + text reply.
    """
    date_te = format_date_telugu(hearing_date_iso)
    if days_before == 2:
        prefix = "మీ విచారణకు రెండు రోజులు ఉన్నాయి."
    elif days_before == 1:
        prefix = "మీ విచారణకు రేపు ఉంది."
    else:
        prefix = "మీ విచారణ ఈరోజు ఉంది."

    return f"{prefix} కేసు నంబర్ {case_id}. తేదీ {date_te}. సమయం {hearing_time}."


def fetch_reminders_for_date(target_date: datetime.date) -> List[Tuple[str, str, str, str]]:
    """
    Returns list of reminders:
    (phone, client_name, case_id, hearing_time)
    """
    conn = db_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT phone, client_name, case_id, hearing_time
        FROM cases
        WHERE hearing_date = ?
    """, (target_date.isoformat(),))
    rows = cur.fetchall()
    conn.close()
    return [(str(p).strip(), str(n).strip(), str(cid).strip(), str(t).strip()) for p, n, cid, t in rows]


def open_chat_by_phone(driver: webdriver.Chrome, db_phone: str):
    """
    Opens chat using WhatsApp 'send' URL (best for automation).
    """
    num = phone_to_whatsapp_send_number(db_phone)
    url = f"https://web.whatsapp.com/send?phone={num}&text&app_absent=0"
    driver.get(url)
    wait_for_whatsapp_ready(driver, timeout=60)


def run_scheduler_tick(driver: webdriver.Chrome, now: datetime.datetime, last_sent_cache: set):
    """
    Checks reminders and sends if not already sent.
    last_sent_cache stores keys (phone|case_id|date|days_before)
    """
    audio_enabled = is_audio_enabled()

    for days_before in REMINDER_DAYS:
        target_date = (now.date() + datetime.timedelta(days=days_before))
        reminders = fetch_reminders_for_date(target_date)

        for phone, client_name, case_id, hearing_time in reminders:
            cache_key = f"{phone}|{case_id}|{target_date.isoformat()}|{days_before}"
            if cache_key in last_sent_cache:
                continue

            # Compose reminder
            text_msg = (
                f"Dear {client_name},\n"
                f"Reminder: Your hearing for Case {case_id} is on {target_date.isoformat()} at {hearing_time}.\n"
                f"- Advocate Office"
            )

            telugu_msg = build_telugu_reminder(case_id, target_date.isoformat(), hearing_time, days_before)

            # Send
            try:
                open_chat_by_phone(driver, phone)
                safe_send_text(driver, text_msg)

                if audio_enabled:
                    audio_path = text_to_audio_mp3(telugu_msg)
                    send_audio_attachment(driver, audio_path)
                    try:
                        os.remove(audio_path)
                    except Exception:
                        pass

                last_sent_cache.add(cache_key)
                print(f"[REMINDER] Sent to {phone} for case {case_id} (D-{days_before})")

            except Exception as e:
                print(f"[REMINDER] Failed for {phone} case {case_id}: {e}")


# ==========================================================
#                 MAIN BOT LOOP
# ==========================================================
def start_whatsapp_bot():
    ensure_settings_table()

    print("\nStarting WhatsApp bot...\n")
    driver = build_driver()

    driver.get("https://web.whatsapp.com")
    print(f"Please scan the QR code (wait ~{QR_WAIT_SECONDS}s)...")
    time.sleep(QR_WAIT_SECONDS)

    # After QR scan, wait for the UI to be ready
    try:
        wait_for_whatsapp_ready(driver, timeout=120)
    except Exception:
        print("WhatsApp Web not ready. Please ensure QR is scanned and chat UI is visible.")
        return

    print("\nBot is listening for messages...\n")

    # Initialize last seen message id to avoid replying to old messages
    last_seen_message_id = None
    try:
        existing = driver.find_elements(By.XPATH, "//div[@data-id and .//div[contains(@class,'message-in')]]")
        if existing:
            last_seen_message_id = existing[-1].get_attribute("data-id")
    except Exception:
        pass

    # Scheduler state
    last_scheduler_check = 0.0
    last_sent_cache = set()
    last_bot_reply = None

    while True:
        time.sleep(POLL_SECONDS)

        # ------------- Scheduled reminders tick -------------
        now_ts = time.time()
        if now_ts - last_scheduler_check >= REMINDER_POLL_SECONDS:
            last_scheduler_check = now_ts
            try:
                run_scheduler_tick(driver, datetime.datetime.now(), last_sent_cache)
            except Exception as e:
                print("[REMINDER] Scheduler tick error:", e)

        # ------------- Incoming message processing -------------
        try:
            # Only incoming messages
            messages = driver.find_elements(By.XPATH, "//div[@data-id and .//div[contains(@class,'message-in')]]")
            if not messages:
                continue

            latest_msg = messages[-1]
            msg_id = latest_msg.get_attribute("data-id")
            # 🚫 Ignore bot's own outgoing messages
            if msg_id.startswith("true_"):
                continue

            if not msg_id or msg_id == last_seen_message_id:
                continue

            # Extract message text
            parts = latest_msg.find_elements(By.XPATH, ".//span[@data-testid='selectable-text']//span")
            if not parts:
                last_seen_message_id = msg_id
                continue

            msg_text = parts[0].text.strip()
            last_seen_message_id = msg_id

            print("\nNew message:", msg_text)

            # sender phone from data-id
            sender_phone = extract_sender_phone_from_data_id(msg_id)

            # Compute reply
            reply = search_case(msg_text, sender_phone)
            print("Reply:", reply)
            if reply == msg_text:
                continue
            last_bot_reply = reply

            # Always send text reply
            safe_send_text(driver, reply)

            # Audio attachment (if enabled + keyword condition)
            audio_enabled = is_audio_enabled()
            if audio_enabled and should_send_audio_for_message(msg_text):
                try:
                    telugu = to_telugu(reply)
                    audio_path = text_to_audio_mp3(telugu)
                    send_audio_attachment(driver, audio_path)
                    try:
                        os.remove(audio_path)
                    except Exception:
                        pass
                    print("Audio attachment sent.")
                except Exception as e:
                    print("Audio send failed:", e)

        except Exception as e:
            print("Loop error:", e)
            continue


if __name__ == "__main__":
    start_whatsapp_bot()
