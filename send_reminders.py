import pandas as pd
import pywhatkit
import datetime as dt
import time
import schedule

CASES_FILE = "advocate_cases.csv"
INDIAN_TZ_OFFSET = 5.5  # if needed later

def load_cases():
    df = pd.read_csv(CASES_FILE)
    # ensure date/time columns are strings
    df["hearing_date"] = df["hearing_date"].astype(str)
    df["hearing_time"] = df["hearing_time"].astype(str)
    return df

def send_whatsapp_message(phone: str, message: str):
    print(f"Sending to {phone}: {message}")
    # instantly sends via web.whatsapp.com (must be logged in)
    pywhatkit.sendwhatmsg_instantly(
        phone_no=phone,
        message=message,
        wait_time=20,   # seconds to wait while opening WhatsApp Web
        tab_close=True,
        close_time=3
    )
    # small sleep to avoid spamming too fast
    time.sleep(5)

def send_tomorrow_reminders():
    today = dt.date.today()
    tomorrow = today + dt.timedelta(days=1)
    tomorrow_str = tomorrow.strftime("%Y-%m-%d")

    df = load_cases()
    # filter cases with hearing_date == tomorrow
    upcoming = df[df["hearing_date"] == tomorrow_str]

    if upcoming.empty:
        print("No hearings tomorrow.")
        return

    for _, row in upcoming.iterrows():
        client = row["client_name"]
        phone = row["phone"]
        case_id = row["case_id"]
        hearing_date = row["hearing_date"]
        hearing_time = row["hearing_time"]

        msg = (
            f"Dear {client},\n"
            f"Reminder: Your next hearing for Case {case_id} is scheduled on "
            f"{hearing_date} at {hearing_time}.\n\n"
            f"- Advocate Office"
        )

        send_whatsapp_message(phone, msg)

def main():
    # schedule the job every day at 09:00
    #schedule.every().day.at("13:15").do(send_tomorrow_reminders)
    schedule.every(1).minutes.do(send_all_reminders)


    print("Scheduler started. Waiting for next run...")
    while True:
        schedule.run_pending()
        time.sleep(1)
        
        

def send_all_reminders():
    today = dt.date.today()

    conn = sqlite3.connect("cases.db")
    cur = conn.cursor()

    cur.execute("SELECT client_name, phone, case_id, hearing_date, hearing_time FROM cases")
    rows = cur.fetchall()

    for client, phone, case_id, hearing_date, hearing_time in rows:

        hearing_dt = dt.datetime.strptime(hearing_date, "%Y-%m-%d").date()
        delta = (hearing_dt - today).days

        if delta == 2:
            msg = f"Reminder: Your hearing for Case {case_id} is in 2 days."
            send_whatsapp_message(phone, msg)

        elif delta == 1:
            msg = f"Reminder: Your hearing for Case {case_id} is tomorrow at {hearing_time}."
            send_whatsapp_message(phone, msg)

        elif delta == 0:
            msg = f"Today is your hearing for Case {case_id} at {hearing_time}."
            send_whatsapp_message(phone, msg)

    conn.close()




#if __name__ == "__main__":
    #main()
if __name__ == "__main__":
    #send_tomorrow_reminders()
    send_all_reminders()
