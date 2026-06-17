import sqlite3
import random
import os
import time
from contextlib import contextmanager
from config import DB_PATH


class Database:
    def __init__(self, db_path=DB_PATH):
        # Ensure the directory exists to avoid Docker volume mounting issues
        os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
        self.db_path = db_path
        self._init_db()

    @contextmanager
    def _get_connection(self):
        """Context manager for database connections."""
        conn = sqlite3.connect(self.db_path)
        try:
            yield conn
        finally:
            conn.close()

    def _init_db(self):
        """Initialize database schema and perform migrations."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            # message_links: tracks which message in receiver's chat maps to which sender
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS message_links (
                    receiver_msg_id INTEGER,
                    receiver_chat_id INTEGER,
                    sender_id INTEGER,
                    sender_msg_id INTEGER,
                    sender_chat_id INTEGER,
                    anon_num TEXT,
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
                cursor.execute(
                    "UPDATE message_links SET created_at = CURRENT_TIMESTAMP WHERE created_at IS NULL"
                )
            if "anon_num" not in columns:
                cursor.execute("ALTER TABLE message_links ADD COLUMN anon_num TEXT")

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
            for col, d_type, d_val in [
                ("receive_media", "INTEGER", 1),
                ("receive_messages", "INTEGER", 1),
                ("auto_voice", "INTEGER", 0),
                ("voice_gender", "TEXT", "'m'"),
                ("skip_confirm_voice", "INTEGER", 0),
                ("skip_confirm_media", "INTEGER", 0),
                ("anon_audio", "INTEGER", 1),
            ]:
                if col not in settings_columns:
                    cursor.execute(
                        f"ALTER TABLE user_settings ADD COLUMN {col} {d_type} DEFAULT {d_val}"
                    )

            cursor.execute(
                "UPDATE user_settings SET anon_audio = 1 WHERE anon_audio IS NULL OR anon_audio = 0"
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
                CREATE TABLE IF NOT EXISTS anon_identities (
                    sender_id INTEGER,
                    receiver_id INTEGER,
                    anon_num TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (sender_id, receiver_id)
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS global_config (
                    key TEXT PRIMARY KEY,
                    value TEXT
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS cooldowns (
                    sender_id INTEGER,
                    receiver_id INTEGER,
                    last_sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (sender_id, receiver_id)
                )
            """)
            conn.commit()

    def save_message_link(
        self,
        receiver_msg_id,
        receiver_chat_id,
        sender_id,
        sender_msg_id,
        sender_chat_id,
        anon_num=None,
        poll_id=None,
    ):
        """Save a link between sent and received messages for reply tracking."""
        with self._get_connection() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO message_links 
                   (receiver_msg_id, receiver_chat_id, sender_id, sender_msg_id, sender_chat_id, anon_num, poll_id, created_at) 
                   VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)""",
                (
                    receiver_msg_id,
                    receiver_chat_id,
                    sender_id,
                    sender_msg_id,
                    sender_chat_id,
                    anon_num,
                    poll_id,
                ),
            )
            conn.commit()

    def get_link_by_receiver(self, msg_id, chat_id):
        """Get sender info by the message ID in the receiver's chat."""
        with self._get_connection() as conn:
            res = conn.execute(
                "SELECT sender_id, sender_msg_id, sender_chat_id, anon_num FROM message_links WHERE receiver_msg_id = ? AND receiver_chat_id = ?",
                (msg_id, chat_id),
            ).fetchone()
            return res

    def get_link_by_poll(self, poll_id):
        """Get sender info linked to a specific poll."""
        with self._get_connection() as conn:
            return conn.execute(
                "SELECT sender_id, receiver_msg_id, receiver_chat_id FROM message_links WHERE poll_id = ?",
                (poll_id,),
            ).fetchone()

    def block_user(self, user_id, sender_id, reason_msg_id=None):
        """Block a sender from writing to a user."""
        with self._get_connection() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO user_blocks (user_id, blocked_sender_id, reason_msg_id) VALUES (?, ?, ?)",
                (user_id, sender_id, reason_msg_id),
            )
            conn.commit()

    def unblock_user(self, user_id, sender_id):
        """Unblock a sender."""
        with self._get_connection() as conn:
            cursor = conn.execute(
                "DELETE FROM user_blocks WHERE user_id = ? AND blocked_sender_id = ?",
                (user_id, sender_id),
            )
            conn.commit()
            return cursor.rowcount > 0

    def unblock_by_index(self, user_id, index):
        """Unblock a user by their index in the blocked list."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            res = cursor.execute(
                "SELECT blocked_sender_id FROM user_blocks WHERE user_id = ? ORDER BY blocked_at ASC LIMIT 1 OFFSET ?",
                (user_id, index - 1),
            ).fetchone()
            if res:
                cursor.execute(
                    "DELETE FROM user_blocks WHERE user_id = ? AND blocked_sender_id = ?",
                    (user_id, res[0]),
                )
                conn.commit()
                return True
            return False

    def is_blocked(self, user_id, sender_id):
        """Check if a sender is blocked by a user."""
        with self._get_connection() as conn:
            return (
                conn.execute(
                    "SELECT 1 FROM user_blocks WHERE user_id = ? AND blocked_sender_id = ?",
                    (user_id, sender_id),
                ).fetchone()
                is not None
            )

    def get_blocked_list(self, user_id):
        """Get list of users blocked by a specific user."""
        with self._get_connection() as conn:
            return conn.execute(
                "SELECT blocked_sender_id, blocked_at, reason_msg_id FROM user_blocks WHERE user_id = ? ORDER BY blocked_at ASC",
                (user_id,),
            ).fetchall()

    def is_sender_anon(self, target_id: int, sender_id: int) -> bool:
        """Check if the sender is the anonymous user in the relationship between target and sender.
        Defaults to True for the very first message initiated via referral link."""
        with self._get_connection() as conn:
            # Check if target initiated the conversation (target is anon, sender is link owner)
            res = conn.execute(
                "SELECT 1 FROM message_links WHERE sender_id = ? AND receiver_chat_id = ?",
                (target_id, sender_id),
            ).fetchone()
            if res:
                return False  # Target initiated, so Sender is the link owner!
            return True  # Either sender initiated, or it's the first message. Either way, sender is Anon.

    def get_user_lang(self, user_id, default="uk"):
        """Get user's selected language."""
        with self._get_connection() as conn:
            res = conn.execute(
                "SELECT lang FROM user_settings WHERE user_id = ?", (user_id,)
            ).fetchone()
            return res[0] if res else default

    def set_user_lang(self, user_id, lang):
        """Set user's language."""
        with self._get_connection() as conn:
            conn.execute(
                "INSERT INTO user_settings (user_id, lang) VALUES (?, ?) ON CONFLICT(user_id) DO UPDATE SET lang = ?",
                (user_id, lang, lang),
            )
            conn.commit()

    def get_user_settings(self, user_id):
        """Get all settings for a user with defaults if not exists."""
        with self._get_connection() as conn:
            cursor = conn.execute(
                "SELECT * FROM user_settings WHERE user_id = ?", (user_id,)
            )
            res = cursor.fetchone()
            if not res:
                return {
                    "user_id": user_id,
                    "lang": "uk",
                    "receive_media": 1,
                    "receive_messages": 1,
                    "auto_voice": 0,
                    "voice_gender": "rnd",
                    "anon_audio": 1,
                    "skip_confirm_voice": 0,
                    "skip_confirm_media": 0,
                }
            columns = [column[0] for column in cursor.description]
            return dict(zip(columns, res))

    def update_user_settings(self, user_id, **kwargs):
        """Batch update user settings."""
        if not kwargs:
            return
        keys = ", ".join([f"{k} = ?" for k in kwargs.keys()])
        values = list(kwargs.values()) + [user_id]
        with self._get_connection() as conn:
            cursor = conn.execute(
                f"UPDATE user_settings SET {keys} WHERE user_id = ?", values
            )
            if cursor.rowcount == 0:
                full_keys = ["user_id"] + list(kwargs.keys())
                full_values = [user_id] + list(kwargs.values())
                placeholders = ", ".join(["?" for _ in full_keys])
                conn.execute(
                    f"INSERT INTO user_settings ({', '.join(full_keys)}) VALUES ({placeholders})",
                    full_values,
                )
            conn.commit()

    def get_admin_stats(self):
        """Get global bot statistics."""
        stats = {}
        with self._get_connection() as conn:
            stats["msg_total"] = conn.execute(
                "SELECT COUNT(*) FROM message_links"
            ).fetchone()[0]
            stats["total_users"] = conn.execute(
                "SELECT COUNT(*) FROM user_settings"
            ).fetchone()[0]
            stats["langs"] = dict(
                conn.execute(
                    "SELECT lang, COUNT(*) FROM user_settings GROUP BY lang"
                ).fetchall()
            )
            stats["total_blocks"] = conn.execute(
                "SELECT COUNT(*) FROM user_blocks"
            ).fetchone()[0]
        return stats

    def check_and_reserve_cooldown(
        self, sender_id: int, receiver_id: int, cd_seconds: int
    ) -> tuple[bool, int]:
        """Check if cooldown is active and update it if allowed. Returns (is_allowed, remaining_seconds)."""
        if cd_seconds <= 0:
            return True, 0
        with self._get_connection() as conn:
            res = conn.execute(
                "SELECT strftime('%s', last_sent_at) FROM cooldowns WHERE sender_id = ? AND receiver_id = ?",
                (sender_id, receiver_id),
            ).fetchone()
            now = int(time.time())
            if res and res[0]:
                last_ts = int(res[0])
                if now - last_ts < cd_seconds:
                    return False, cd_seconds - (now - last_ts)
            conn.execute(
                "INSERT OR REPLACE INTO cooldowns (sender_id, receiver_id, last_sent_at) VALUES (?, ?, CURRENT_TIMESTAMP)",
                (sender_id, receiver_id),
            )
            conn.commit()
            return True, 0

    def get_or_create_anon_num(self, receiver_id: int, sender_id: int) -> str:
        """Find or create a DIRECTIONAL anonymous number for sender->receiver pair.
        A->B and B->A will have different numbers."""
        with self._get_connection() as conn:
            res = conn.execute(
                "SELECT anon_num FROM anon_identities WHERE sender_id = ? AND receiver_id = ?",
                (sender_id, receiver_id),
            ).fetchone()
            if res:
                return res[0]

            # Pick a number not used by this receiver recently
            cursor = conn.execute(
                "SELECT anon_num FROM anon_identities WHERE receiver_id = ? AND updated_at > datetime('now', '-30 days')",
                (receiver_id,),
            )
            taken_nums = {row[0] for row in cursor.fetchall()}

            pool = [f"№{i:03d}" for i in range(1, 1000)]
            available = [n for n in pool if n not in taken_nums]
            picked = (
                random.choice(available)
                if available
                else f"№{random.randint(1000, 9999):03d}"
            )

            conn.execute(
                "INSERT OR REPLACE INTO anon_identities (sender_id, receiver_id, anon_num) VALUES (?, ?, ?)",
                (sender_id, receiver_id, picked),
            )
            conn.commit()

        # Also keep active_sessions updated for session management
        self.update_session(sender_id, receiver_id, picked)
        return picked

    def update_session(self, sender_id: int, receiver_id: int, anon_num: str = None):
        """Register or update a shared session for a user pair."""
        u1, u2 = sorted([sender_id, receiver_id])
        with self._get_connection() as conn:
            if anon_num:
                conn.execute(
                    "INSERT INTO active_sessions (user_a, user_b, anon_num, updated_at) VALUES (?, ?, ?, CURRENT_TIMESTAMP) ON CONFLICT(user_a, user_b) DO UPDATE SET anon_num = excluded.anon_num, updated_at = CURRENT_TIMESTAMP",
                    (u1, u2, anon_num),
                )
            else:
                conn.execute(
                    "UPDATE active_sessions SET updated_at = CURRENT_TIMESTAMP WHERE user_a = ? AND user_b = ?",
                    (u1, u2),
                )
            conn.commit()

    def delete_session(self, user_id_1: int, user_id_2: int):
        """Delete a shared session."""
        u1, u2 = sorted([user_id_1, user_id_2])
        with self._get_connection() as conn:
            conn.execute(
                "DELETE FROM active_sessions WHERE user_a = ? AND user_b = ?", (u1, u2)
            )
            conn.commit()

    def get_global_config(self, key: str, default=None):
        """Get a global configuration value."""
        with self._get_connection() as conn:
            res = conn.execute(
                "SELECT value FROM global_config WHERE key = ?", (key,)
            ).fetchone()
            return res[0] if res else default

    def set_global_config(self, key: str, value):
        """Set a global configuration value."""
        with self._get_connection() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO global_config (key, value) VALUES (?, ?)",
                (key, str(value)),
            )
            conn.commit()

    def get_last_msg_timestamp(self, sender_id: int, receiver_id: int) -> int:
        """Get timestamp of the last message between users in seconds."""
        with self._get_connection() as conn:
            res = conn.execute(
                "SELECT strftime('%s', created_at) FROM message_links WHERE sender_id = ? AND receiver_chat_id = ? ORDER BY created_at DESC LIMIT 1",
                (sender_id, receiver_id),
            ).fetchone()
            return int(res[0]) if res and res[0] else 0

    def increment_global_config(self, key, amount: int):
        """Increment a global configuration value atomically."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            res = cursor.execute(
                "SELECT value FROM global_config WHERE key = ?", (key,)
            ).fetchone()
            current = int(res[0]) if res and res[0] else 0
            new_val = current + amount
            cursor.execute(
                "INSERT OR REPLACE INTO global_config (key, value) VALUES (?, ?)",
                (key, str(new_val)),
            )
            conn.commit()
            return new_val


db = Database()
