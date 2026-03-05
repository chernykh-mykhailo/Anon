import asyncio
import logging
import sqlite3
from aiogram import Bot
from aiogram.fsm.storage.base import StorageKey
from database import db


async def clean_stale_sessions(bot: Bot, storage):
    """
    Background task that clears DB sessions and FSM state for expired users.
    Runs every 60 seconds. Respects session_time from global_config.
    """
    while True:
        try:
            session_minutes = int(db.get_global_config("session_time", "5"))

            if session_minutes > 0:
                with sqlite3.connect(db.db_path) as conn:
                    cursor = conn.cursor()
                    cursor.execute(
                        f"SELECT user_a, user_b FROM active_sessions "
                        f"WHERE updated_at < datetime('now', '-{session_minutes} minutes')"
                    )
                    expired_pairs = cursor.fetchall()

                for u1, u2 in expired_pairs:
                    for user_id in [u1, u2]:
                        key = StorageKey(
                            bot_id=bot.id, chat_id=user_id, user_id=user_id
                        )
                        data = await storage.get_data(key)
                        current_target = data.get("target_id")
                        if current_target in [u1, u2] and current_target != user_id:
                            await storage.set_state(key, None)
                            await storage.set_data(key, {})

                    db.delete_session(u1, u2)

        except Exception as e:
            logging.error(f"Error in session cleaner: {e}")

        await asyncio.sleep(60)  # Check every minute
