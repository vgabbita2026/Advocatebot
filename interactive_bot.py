# interactive_bot.py

import time
import re
import sqlite3
import datetime
from selenium import webdriver
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager


DB_FILE = "cases.db"


# ==========================================================
#        PHONE NORMALIZER (CRITICAL FOR CORRECT HISTORY)
# ==========================================================
def normalize_phone(sender_phone):
    """
    Normalize WhatsApp sender phone by matching LAST 10 DIGITS.
    This handles WhatsApp internal prefixes correctly.
    """

    if not sender_phone:
        return None

    # Extract digits from WhatsApp sender
    sender_digits = re.sub(r"\D", "", sender_phone)

    # Keep only last 10 digits (actual mobile number)
    if len(sender_digits) < 10:
        return None
    sender_last10 = sender_digits[-10:]

    print("DEBUG: sender last10 digits:", sender_last10)

    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("SELECT phone FROM cases")
    db_phones = [row[0] for row in cur.fetchall()]
    conn.close()

    for db_phone in db_phones:
        db_digits = re.sub(r"\D", "", db_phone)
        if len(db_digits) >= 10:
            db_last10 = db_digits[-10:]
            if db_last10 == sender_last10:
                print("DEBUG: PHONE MATCHED IN DB:", db_phone)
                return db_phone

    print("DEBUG: PHONE NOT FOUND IN DB for:", sender_phone)
    return None




# ==========================================================
#             SEARCH LOGIC (UNIT-TEST VERIFIED)
# ==========================================================
def search_case(query_text, sender_phone):
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()

    query_text = query_text.lower().strip()
    print("DEBUG: Query:", query_text)
    print("DEBUG: Sender raw:", sender_phone)

    sender_phone = normalize_phone(sender_phone)
    if not sender_phone:
        return "Your number is not registered in the system."

    print("DEBUG: Normalized sender phone:", sender_phone)

    # Extract case number
    match = re.search(r"\b(\d{3,10})\b", query_text)
    case_id = match.group(1) if match else None

    # =========================
    # CASE HISTORY (FIRST!)
    # =========================
    if ("history" in query_text or
        "all hearings" in query_text or
        "hearing history" in query_text or
        "full history" in query_text):

        cur.execute("""
            SELECT case_id, hearing_date, hearing_time
            FROM cases
            WHERE phone = ?
            ORDER BY hearing_date ASC
        """, (sender_phone,))
        rows = cur.fetchall()
        conn.close()

        if not rows:
            return "No hearing history found."

        text = "Your Case Hearing History:\n"
        for cid, d, t in rows:
            text += f"Case {cid}: {d} at {t}\n"
        return text.strip()

    # =========================
    # NEXT HEARING
    # =========================
    if "next hearing" in query_text or query_text == "hearing":

        cur.execute("""
            SELECT case_id, hearing_date, hearing_time
            FROM cases
            WHERE phone = ?
        """, (sender_phone,))
        rows = cur.fetchall()
        conn.close()

        today = datetime.date.today()
        upcoming = []

        for cid, date_str, time_ in rows:
            try:
                d = datetime.date.fromisoformat(str(date_str).strip())
                if d >= today:
                    upcoming.append((d, cid, time_))
            except:
                pass

        if not upcoming:
            return "You have no upcoming hearings."

        upcoming.sort()
        d, cid, t = upcoming[0]
        return f"Your next hearing:\nCase {cid}\nDate: {d} at {t}"

    # =========================
    # CASE LOOKUP
    # =========================
    if case_id:
        cur.execute("""
            SELECT hearing_date, hearing_time
            FROM cases
            WHERE case_id = ?
            ORDER BY hearing_date ASC
        """, (case_id,))
        rows = cur.fetchall()
        conn.close()

        if not rows:
            return "Case not found."

        text = f"Case {case_id} Hearings:\n"
        for d, t in rows:
            text += f"- {d} at {t}\n"
        return text.strip()

    conn.close()
    return "I didn't understand. Try: 'next hearing', 'case history', or 'case 12345'."



# ==========================================================
#                WHATSAPP BOT WITH SELENIUM
# ==========================================================
def start_whatsapp_bot():

    print("\nStarting WhatsApp bot...\n")

    options = Options()
    options.add_argument("--disable-infobars")
    options.add_argument("--start-maximized")
    options.binary_location = r"C:\Program Files\Google\Chrome\Application\chrome.exe"

    driver = webdriver.Chrome(
        service=Service(ChromeDriverManager().install()),
        options=options
    )

    driver.get("https://web.whatsapp.com")
    print("Please scan the QR code...")
    time.sleep(15)

    print("\nBot is listening for messages...\n")

    last_text = ""

    while True:
        time.sleep(1.5)

        try:
            # ---------------- Find message rows ----------------
            messages = driver.find_elements(
                By.XPATH,
                "//div[@data-id and .//div[contains(@class,'message-in')]]"
            )
            if not messages:
                continue

            latest_msg = messages[-1]

            # ---------------- Extract message text ----------------
            msg_text_elements = latest_msg.find_elements(
                By.XPATH,
                ".//span[@data-testid='selectable-text']//span"
            )
            if not msg_text_elements:
                continue

            msg_text = msg_text_elements[0].text.strip()
            if msg_text == last_text:
                continue

            print("\nNew message received:", msg_text)
            last_text = msg_text

            # ---------------- Extract sender phone ----------------
            data_id = latest_msg.get_attribute("data-id")
            print("DEBUG: data-id:", data_id)

            sender_phone = None
            match = re.search(r"false_(\d+)@c\.us", data_id)
            if match:
                sender_phone = "+" + match.group(1)

            print("DEBUG: Extracted sender phone =", sender_phone)

            # ---------------- Compute reply ----------------
            reply = search_case(msg_text.lower(), sender_phone)
            print("DEBUG: Reply =", reply)

            # ---------------- Send reply ----------------
            input_box = driver.find_element(
                By.XPATH,
                "//div[@contenteditable='true' and contains(@aria-label,'Type')]"
            )

            input_box.click()
            time.sleep(0.2)
            input_box.send_keys(reply)
            time.sleep(0.2)
            input_box.send_keys(Keys.ENTER)

            print("Sent reply.\n")

        except Exception as e:
            print("Error:", e)
            continue


# ==========================================================
#                        START BOT
# ==========================================================
if __name__ == "__main__":
    start_whatsapp_bot()
