import sqlite3


class Database:
    def __init__(self, db_path="anon_bot.db"):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            # message_links: tracks which message in receiver's chat maps to which sender
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS message_links (
                    receiver_msg_id INTEGER,
                    receiver_chat_id INTEGER,
                    sender_id INTEGER,
                    sender_msg_id INTEGER,
                    sender_chat_id INTEGER,
                    poll_id TEXT,
                    PRIMARY KEY (receiver_msg_id, receiver_chat_id)
                )
            """)

            # Check if columns exist (for migration)
            cursor.execute("PRAGMA table_info(message_links)")
            columns = [column[1] for column in cursor.fetchall()]

            if "sender_msg_id" not in columns:
                cursor.execute(
                    "ALTER TABLE message_links ADD COLUMN sender_msg_id INTEGER"
                )
            if "sender_chat_id" not in columns:
                cursor.execute(
                    "ALTER TABLE message_links ADD COLUMN sender_chat_id INTEGER"
                )
            if "receiver_msg_id" not in columns:
                # This is a critical failure if this happens, usually means the table structure is ancient
                # But we try to handle it by renaming or recreate if it was 'received_msg_id'
                if "received_msg_id" in columns:
                    cursor.execute(
                        "ALTER TABLE message_links RENAME COLUMN received_msg_id TO receiver_msg_id"
                    )
                if "receiver_chat_id" not in columns and "receiver_id" in columns:
                    cursor.execute(
                        "ALTER TABLE message_links RENAME COLUMN receiver_id TO receiver_chat_id"
                    )

            if "poll_id" not in columns:
                cursor.execute("ALTER TABLE message_links ADD COLUMN poll_id TEXT")

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS user_blocks (
                    user_id INTEGER,
                    blocked_sender_id INTEGER,
                    PRIMARY KEY (user_id, blocked_sender_id)
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS user_settings (
                    user_id INTEGER PRIMARY KEY,
                    lang TEXT DEFAULT 'uk'
                )
            """)
            conn.commit()

    def save_link(
        self,
        receiver_msg_id,
        receiver_chat_id,
        sender_id,
        sender_msg_id,
        sender_chat_id,
        poll_id=None,
    ):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """INSERT OR REPLACE INTO message_links 
                   (receiver_msg_id, receiver_chat_id, sender_id, sender_msg_id, sender_chat_id, poll_id) 
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    receiver_msg_id,
                    receiver_chat_id,
                    sender_id,
                    sender_msg_id,
                    sender_chat_id,
                    poll_id,
                ),
            )
            conn.commit()

    def get_link_by_poll(self, poll_id):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT sender_id, sender_msg_id, sender_chat_id FROM message_links WHERE poll_id = ?",
                (poll_id,),
            )
            return cursor.fetchone()

    def get_link_by_receiver(self, receiver_msg_id, receiver_chat_id):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT sender_id, sender_msg_id, sender_chat_id FROM message_links WHERE receiver_msg_id = ? AND receiver_chat_id = ?",
                (receiver_msg_id, receiver_chat_id),
            )
            return cursor.fetchone()

    def set_user_lang(self, user_id, lang):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT OR REPLACE INTO user_settings (user_id, lang) VALUES (?, ?)",
                (user_id, lang),
            )
            conn.commit()

    def get_user_lang(self, user_id, default="uk"):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT lang FROM user_settings WHERE user_id = ?", (user_id,)
            )
            result = cursor.fetchone()
            return result[0] if result else default

    def block_user(self, user_id, sender_to_block):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT OR IGNORE INTO user_blocks (user_id, blocked_sender_id) VALUES (?, ?)",
                (user_id, sender_to_block),
            )
            conn.commit()

    def is_blocked(self, user_id, sender_id):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT 1 FROM user_blocks WHERE user_id = ? AND blocked_sender_id = ?",
                (user_id, sender_id),
            )
            return cursor.fetchone() is not None


db = Database()
