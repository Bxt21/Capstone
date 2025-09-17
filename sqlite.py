import sqlite3

DB_PATH = "signs.db"

LETTERS = list("ABCDEFGHIJKLMNOPQRSTUVWXYZ") + ["NG", "Ñ"]

WORDS = [
    "AGAIN", "DEAF", "DONT", "DRINK", "EAT", "FOOD", "FROM",
    "HARD_OF_HEARING", "HELLO", "HERE", "HOW_MUCH", "HUNGRY", "LIVE",
    "ME", "MEET", "NAME", "NICE", "NO", "SORRY", "THANK_YOU",
    "THEM", "UNDERSTAND", "WAIT", "WELCOME", "WHAT", "WHEN", "WHERE",
    "WHO", "WHY", "YES", "YOU"
]

# Phrase -> Gesture mapping
PHRASE_MAPPING = {
    "I_AM": ["ME"],
    "MY": ["ME"],
    "WHAT_IS": ["WHAT"],
    "WHATS": ["WHAT"],
    "YOUR": ["YOU"]
}

def create_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # Drop old tables if they exist
    c.execute("DROP TABLE IF EXISTS gestures")
    c.execute("DROP TABLE IF EXISTS signs")

    # Create tables
    c.execute("""
        CREATE TABLE signs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL
        )
    """)
    c.execute("""
        CREATE TABLE gestures (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sign_id INTEGER NOT NULL,
            gesture_path TEXT NOT NULL,
            FOREIGN KEY(sign_id) REFERENCES signs(id)
        )
    """)

    # Insert letters + words
    for sign in LETTERS + WORDS:
        c.execute("INSERT INTO signs (name) VALUES (?)", (sign,))
        sign_id = c.lastrowid
        gesture_path = f"Gestures/{sign}"
        c.execute("INSERT INTO gestures (sign_id, gesture_path) VALUES (?, ?)", (sign_id, gesture_path))

    # Insert phrases with mapped gestures
    for phrase, gestures in PHRASE_MAPPING.items():
        c.execute("INSERT INTO signs (name) VALUES (?)", (phrase,))
        sign_id = c.lastrowid
        for gesture in gestures:
            gesture_path = f"Gestures/{gesture}"
            c.execute("INSERT INTO gestures (sign_id, gesture_path) VALUES (?, ?)", (sign_id, gesture_path))

    conn.commit()
    conn.close()
    print(f"✅ Database created at {DB_PATH} with phrases mapped to correct gestures")

if __name__ == "__main__":
    create_db()
