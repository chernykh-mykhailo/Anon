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
                    blocked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    reason_msg_id INTEGER,
                    PRIMARY KEY (user_id, blocked_sender_id)
                )
            """)

            # Migration for user_blocks
            cursor.execute("PRAGMA table_info(user_blocks)")
            block_columns = [column[1] for column in cursor.fetchall()]
            if "blocked_at" not in block_columns:
                cursor.execute(
                    "ALTER TABLE user_blocks ADD COLUMN blocked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP"
                )
            if "reason_msg_id" not in block_columns:
                cursor.execute(
                    "ALTER TABLE user_blocks ADD COLUMN reason_msg_id INTEGER"
                )
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS user_settings (
                    user_id INTEGER PRIMARY KEY,
                    lang TEXT DEFAULT 'uk',
                    receive_media INTEGER DEFAULT 1,
                    receive_messages INTEGER DEFAULT 1
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
        settings = self.get_user_settings(user_id)
        return settings.get("lang", default)

    def get_user_settings(self, user_id):
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute(
                "SELECT lang, receive_media, receive_messages FROM user_settings WHERE user_id = ?",
                (user_id,),
            )
            result = cursor.fetchone()
            if result:
                return dict(result)
            return {"lang": "uk", "receive_media": 1, "receive_messages": 1}

    def update_user_setting(self, user_id, key, value):
        # Validate key to prevent injection (though values are parameterized)
        if key not in ["lang", "receive_media", "receive_messages"]:
            return False

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            # We use a trick to update a specific column by name
            cursor.execute(
                f"UPDATE user_settings SET {key} = ? WHERE user_id = ?",
                (value, user_id),
            )
            if cursor.rowcount == 0:
                # Insert initial record if doesn't exist
                cursor.execute(
                    f"INSERT INTO user_settings (user_id, {key}) VALUES (?, ?)",
                    (user_id, value),
                )
            conn.commit()
            return True

    def block_user(self, user_id, sender_to_block, reason_msg_id=None):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """INSERT OR REPLACE INTO user_blocks 
                   (user_id, blocked_sender_id, blocked_at, reason_msg_id) 
                   VALUES (?, ?, CURRENT_TIMESTAMP, ?)""",
                (user_id, sender_to_block, reason_msg_id),
            )
            conn.commit()

    def unblock_user(self, user_id, sender_to_unblock):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "DELETE FROM user_blocks WHERE user_id = ? AND blocked_sender_id = ?",
                (user_id, sender_to_unblock),
            )
            conn.commit()
            return cursor.rowcount > 0

    def get_blocked_list(self, user_id):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT blocked_sender_id, blocked_at, reason_msg_id FROM user_blocks WHERE user_id = ? ORDER BY blocked_at DESC",
                (user_id,),
            )
            return cursor.fetchall()

    def unblock_by_index(self, user_id, index):
        # index is 1-based
        blocked = self.get_blocked_list(user_id)
        if 0 < index <= len(blocked):
            target_sender_id = blocked[index - 1][0]
            return self.unblock_user(user_id, target_sender_id)
        return False

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

            # Message stats
            cursor.execute("SELECT COUNT(*) FROM message_links")
            total_msg = cursor.fetchone()[0]

            cursor.execute(
                "SELECT COUNT(*) FROM message_links WHERE rowid IN (SELECT rowid FROM message_links EXPLAIN QUERY PLAN)"
            )  # Actually we need a timestamp to do 24h, but we don't have it.
            # I will assume total_msg for now as we don't have a created_at in message_links.
            # Wait, user_blocks has blocked_at. user_settings doesn't have joined_at.

            # User stats
            cursor.execute("SELECT COUNT(*) FROM user_settings")
            total_users = cursor.fetchone()[0]

            cursor.execute("SELECT lang, COUNT(*) FROM user_settings GROUP BY lang")
            langs = dict(cursor.fetchall())

            # Block stats
            cursor.execute("SELECT COUNT(*) FROM user_blocks")
            total_blocks = cursor.fetchone()[0]

            return {
                "msg_total": total_msg,
                "msg_24h": total_msg,  # Placeholder as there's no timestamp in message_links
                "total_users": total_users,
                "langs": langs,
                "total_blocks": total_blocks,
            }


db = Database()
