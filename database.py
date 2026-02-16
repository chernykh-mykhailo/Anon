import sqlite3
from datetime import datetime


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
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
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
            if "created_at" not in columns:
                cursor.execute(
                    "ALTER TABLE message_links ADD COLUMN created_at TIMESTAMP"
                )

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
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS gemini_keys (
                    user_id INTEGER PRIMARY KEY,
                    api_key TEXT NOT NULL,
                    added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    is_active INTEGER DEFAULT 1,
                    fail_count INTEGER DEFAULT 0
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
                   (receiver_msg_id, receiver_chat_id, sender_id, sender_msg_id, sender_chat_id, poll_id, created_at) 
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    receiver_msg_id,
                    receiver_chat_id,
                    sender_id,
                    sender_msg_id,
                    sender_chat_id,
                    poll_id,
                    datetime.now(),
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

    def get_admin_stats(self):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()

            # 1. Total messages in last 24h
            cursor.execute(
                "SELECT COUNT(*) FROM message_links WHERE created_at >= datetime('now', '-1 day')"
            )
            msg_24h = cursor.fetchone()[0]

            # 2. Total messages all time
            cursor.execute("SELECT COUNT(*) FROM message_links")
            msg_total = cursor.fetchone()[0]

            # 3. Languages usage
            cursor.execute("SELECT lang, COUNT(*) FROM user_settings GROUP BY lang")
            langs = cursor.fetchall()

            # 4. Total users
            cursor.execute("SELECT COUNT(*) FROM user_settings")
            total_users = cursor.fetchone()[0]

            # 5. Total blocks
            cursor.execute("SELECT COUNT(*) FROM user_blocks")
            total_blocks = cursor.fetchone()[0]

            return {
                "msg_24h": msg_24h,
                "msg_total": msg_total,
                "langs": dict(langs),
                "total_users": total_users,
                "total_blocks": total_blocks,
            }

    # === Gemini Key Pool ===

    def save_gemini_key(self, user_id: int, api_key: str):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """INSERT OR REPLACE INTO gemini_keys (user_id, api_key, added_at, is_active, fail_count)
                   VALUES (?, ?, ?, 1, 0)""",
                (user_id, api_key, datetime.now()),
            )
            conn.commit()

    def get_random_gemini_key(self) -> str | None:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT api_key FROM gemini_keys WHERE is_active = 1 ORDER BY RANDOM() LIMIT 1"
            )
            result = cursor.fetchone()
            return result[0] if result else None

    def mark_gemini_key_failed(self, api_key: str):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE gemini_keys SET fail_count = fail_count + 1 WHERE api_key = ?",
                (api_key,),
            )
            # Deactivate after 5 consecutive failures
            conn.execute(
                "UPDATE gemini_keys SET is_active = 0 WHERE api_key = ? AND fail_count >= 5",
                (api_key,),
            )
            conn.commit()

    def remove_gemini_key(self, user_id: int) -> bool:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM gemini_keys WHERE user_id = ?", (user_id,))
            conn.commit()
            return cursor.rowcount > 0

    def get_gemini_key_count(self) -> int:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM gemini_keys WHERE is_active = 1")
            return cursor.fetchone()[0]


db = Database()
