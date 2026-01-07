import sqlite3

def create_db():
    conn = sqlite3.connect("cases.db")
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS cases (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        client_name TEXT NOT NULL,
        phone TEXT NOT NULL,
        case_id TEXT NOT NULL,
        hearing_date TEXT NOT NULL,
        hearing_time TEXT NOT NULL
    )
    """)

    conn.commit()
    conn.close()
    print("Database and table created successfully.")

if __name__ == "__main__":
    create_db()
