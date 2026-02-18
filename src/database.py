import sqlite3
import random
import os
import time


class Database:
    def __init__(self, db_path="data/anon_bot.db"):
        # Ensure the directory exists to avoid Docker volume mounting issues
        os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
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
            if "poll_id" not in columns:
                cursor.execute("ALTER TABLE message_links ADD COLUMN poll_id TEXT")
            if "created_at" not in columns:
                cursor.execute(
                    "ALTER TABLE message_links ADD COLUMN created_at TIMESTAMP"
                )
                # Optionally backfill
                cursor.execute(
                    "UPDATE message_links SET created_at = CURRENT_TIMESTAMP WHERE created_at IS NULL"
                )

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS user_blocks (
                    user_id INTEGER,
                    blocked_sender_id INTEGER,
                    blocked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    reason_msg_id INTEGER,
                    PRIMARY KEY (user_id, blocked_sender_id)
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS user_settings (
                    user_id INTEGER PRIMARY KEY,
                    lang TEXT DEFAULT 'uk',
                    receive_media INTEGER DEFAULT 1,
                    receive_messages INTEGER DEFAULT 1,
                    auto_voice INTEGER DEFAULT 0,
                    voice_gender TEXT DEFAULT 'm',
                    skip_confirm_voice INTEGER DEFAULT 0,
                    skip_confirm_media INTEGER DEFAULT 0
                )
            """)

            # Migration for user_settings
            cursor.execute("PRAGMA table_info(user_settings)")
            settings_columns = [column[1] for column in cursor.fetchall()]
            if "receive_media" not in settings_columns:
                cursor.execute(
                    "ALTER TABLE user_settings ADD COLUMN receive_media INTEGER DEFAULT 1"
                )
            if "receive_messages" not in settings_columns:
                cursor.execute(
                    "ALTER TABLE user_settings ADD COLUMN receive_messages INTEGER DEFAULT 1"
                )
            if "auto_voice" not in settings_columns:
                cursor.execute(
                    "ALTER TABLE user_settings ADD COLUMN auto_voice INTEGER DEFAULT 0"
                )
            if "voice_gender" not in settings_columns:
                cursor.execute(
                    "ALTER TABLE user_settings ADD COLUMN voice_gender TEXT DEFAULT 'm'"
                )
            if "skip_confirm_voice" not in settings_columns:
                cursor.execute(
                    "ALTER TABLE user_settings ADD COLUMN skip_confirm_voice INTEGER DEFAULT 0"
                )
            if "skip_confirm_media" not in settings_columns:
                cursor.execute(
                    "ALTER TABLE user_settings ADD COLUMN skip_confirm_media INTEGER DEFAULT 0"
                )

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS active_sessions (
                    user_a INTEGER,
                    user_b INTEGER,
                    anon_num TEXT,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (user_a, user_b)
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS global_config (
                    key TEXT PRIMARY KEY,
                    value TEXT
                )
            """)

            # Cooldown tracking table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS cooldowns (
                    sender_id INTEGER,
                    receiver_id INTEGER,
                    last_sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (sender_id, receiver_id)
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
                   VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)""",
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

    def get_link_by_receiver(self, msg_id, chat_id):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT sender_id, sender_msg_id, sender_chat_id FROM message_links WHERE receiver_msg_id = ? AND receiver_chat_id = ?",
                (msg_id, chat_id),
            )
            return cursor.fetchone()

    def get_link_by_poll(self, poll_id):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT sender_id, receiver_msg_id, receiver_chat_id FROM message_links WHERE poll_id = ?",
                (poll_id,),
            )
            return cursor.fetchone()

    def block_user(self, user_id, sender_id, reason_msg_id=None):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT OR REPLACE INTO user_blocks (user_id, blocked_sender_id, reason_msg_id) VALUES (?, ?, ?)",
                (user_id, sender_id, reason_msg_id),
            )
            conn.commit()

    def unblock_user(self, user_id, sender_id):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "DELETE FROM user_blocks WHERE user_id = ? AND blocked_sender_id = ?",
                (user_id, sender_id),
            )
            conn.commit()
            return cursor.rowcount > 0

    def unblock_by_index(self, user_id, index):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT blocked_sender_id FROM user_blocks WHERE user_id = ? ORDER BY blocked_at ASC LIMIT 1 OFFSET ?",
                (user_id, index - 1),
            )
            res = cursor.fetchone()
            if res:
                cursor.execute(
                    "DELETE FROM user_blocks WHERE user_id = ? AND blocked_sender_id = ?",
                    (user_id, res[0]),
                )
                conn.commit()
                return True
            return False

    def is_blocked(self, user_id, sender_id):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT 1 FROM user_blocks WHERE user_id = ? AND blocked_sender_id = ?",
                (user_id, sender_id),
            )
            return cursor.fetchone() is not None

    def get_blocked_list(self, user_id):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT blocked_sender_id, blocked_at, reason_msg_id FROM user_blocks WHERE user_id = ? ORDER BY blocked_at ASC",
                (user_id,),
            )
            return cursor.fetchall()

    def get_user_lang(self, user_id, default="uk"):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT lang FROM user_settings WHERE user_id = ?", (user_id,)
            )
            res = cursor.fetchone()
            return res[0] if res else default

    def set_user_lang(self, user_id, lang):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO user_settings (user_id, lang) VALUES (?, ?) ON CONFLICT(user_id) DO UPDATE SET lang = ?",
                (user_id, lang, lang),
            )
            conn.commit()

    def get_user_settings(self, user_id):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM user_settings WHERE user_id = ?", (user_id,))
            res = cursor.fetchone()
            if not res:
                return {
                    "user_id": user_id,
                    "lang": "uk",
                    "receive_media": 1,
                    "receive_messages": 1,
                    "auto_voice": 0,
                    "voice_gender": "m",
                    "skip_confirm_voice": 0,
                    "skip_confirm_media": 0,
                }
            columns = [column[0] for column in cursor.description]
            return dict(zip(columns, res))

    def update_user_settings(self, user_id, **kwargs):
        if not kwargs:
            return
        keys = ", ".join([f"{k} = ?" for k in kwargs.keys()])
        values = list(kwargs.values()) + [user_id]
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(f"UPDATE user_settings SET {keys} WHERE user_id = ?", values)
            if cursor.rowcount == 0:
                full_keys = ["user_id"] + list(kwargs.keys())
                full_values = [user_id] + list(kwargs.values())
                placeholders = ", ".join(["?" for _ in full_keys])
                cursor.execute(
                    f"INSERT INTO user_settings ({', '.join(full_keys)}) VALUES ({placeholders})",
                    full_values,
                )
            conn.commit()

    def get_admin_stats(self):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM message_links")
            msg_total = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM user_settings")
            total_users = cursor.fetchone()[0]

            cursor.execute("SELECT lang, COUNT(*) FROM user_settings GROUP BY lang")
            langs = dict(cursor.fetchall())

            cursor.execute("SELECT COUNT(*) FROM user_blocks")
            total_blocks = cursor.fetchone()[0]

            return {
                "msg_total": msg_total,
                "total_users": total_users,
                "langs": langs,
                "total_blocks": total_blocks,
            }

    def check_and_reserve_cooldown(
        self, sender_id: int, receiver_id: int, cd_seconds: int
    ) -> tuple[bool, int]:
        """Check if cooldown is active and update it if allowed. Returns (is_allowed, remaining_seconds)."""
        if cd_seconds <= 0:
            return True, 0

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT strftime('%s', last_sent_at) FROM cooldowns WHERE sender_id = ? AND receiver_id = ?",
                (sender_id, receiver_id),
            )
            res = cursor.fetchone()
            now = int(time.time())

            if res and res[0]:
                last_ts = int(res[0])
                diff = now - last_ts
                if diff < cd_seconds:
                    return False, cd_seconds - diff

            # If we are here, it's allowed. Update the timestamp immediately to reserve the slot.
            cursor.execute(
                "INSERT OR REPLACE INTO cooldowns (sender_id, receiver_id, last_sent_at) VALUES (?, ?, CURRENT_TIMESTAMP)",
                (sender_id, receiver_id),
            )
            conn.commit()
            return True, 0

    def get_available_anon_num(self, target_id: int, sender_id: int) -> str:
        """Find or create a persistent random number for this pair of users."""
        u1, u2 = sorted([target_id, sender_id])

        # 1. First check if a number is already assigned
        existing_num = None
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT anon_num FROM active_sessions WHERE user_a = ? AND user_b = ?",
                (u1, u2),
            )
            res = cursor.fetchone()
            if res:
                existing_num = res[0]

        if existing_num:
            self.update_session(sender_id, target_id)
            return existing_num

        # 2. If not, find a new one
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT anon_num FROM active_sessions 
                WHERE (user_a = ? OR user_b = ?) 
                AND NOT (user_a = ? AND user_b = ?)
                AND updated_at > datetime('now', '-24 hours')
                """,
                (target_id, target_id, u1, u2),
            )
            taken_nums = {row[0] for row in cursor.fetchall()}

            pool = [f"№{i:03d}" for i in range(1, 457)]
            available = [n for n in pool if n not in taken_nums]

            if not available:
                picked = f"№{random.randint(1, 456):03d}"
            else:
                picked = random.choice(available)

        self.update_session(sender_id, target_id, picked)
        return picked

    def update_session(self, sender_id: int, receiver_id: int, anon_num: str = None):
        """Register or update a shared session for a user pair."""
        u1, u2 = sorted([sender_id, receiver_id])
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            if anon_num:
                cursor.execute(
                    """
                    INSERT INTO active_sessions (user_a, user_b, anon_num, updated_at)
                    VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(user_a, user_b) DO UPDATE SET 
                        anon_num = excluded.anon_num,
                        updated_at = CURRENT_TIMESTAMP
                    """,
                    (u1, u2, anon_num),
                )
            else:
                cursor.execute(
                    "UPDATE active_sessions SET updated_at = CURRENT_TIMESTAMP WHERE user_a = ? AND user_b = ?",
                    (u1, u2),
                )
            conn.commit()

    def delete_session(self, user_id_1: int, user_id_2: int):
        """Delete a shared session (e.g. on /cancel)."""
        u1, u2 = sorted([user_id_1, user_id_2])
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "DELETE FROM active_sessions WHERE user_a = ? AND user_b = ?", (u1, u2)
            )
            conn.commit()

    def get_global_config(self, key: str, default=None):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT value FROM global_config WHERE key = ?", (key,))
            res = cursor.fetchone()
            return res[0] if res else default

    def set_global_config(self, key: str, value):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT OR REPLACE INTO global_config (key, value) VALUES (?, ?)",
                (key, str(value)),
            )
            conn.commit()

    def get_last_msg_timestamp(self, sender_id: int, receiver_id: int) -> int:
        """Get timestamp of the last message from this sender to this receiver in seconds."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT strftime('%s', created_at) FROM message_links 
                WHERE sender_id = ? AND receiver_chat_id = ? 
                ORDER BY created_at DESC LIMIT 1
                """,
                (sender_id, receiver_id),
            )
            res = cursor.fetchone()
            if res and res[0]:
                return int(res[0])
            return 0


db = Database()
