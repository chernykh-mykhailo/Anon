import os
from dotenv import load_dotenv

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", 0))
REPORT_CHAT_ID = int(os.getenv("REPORT_CHAT_ID", 0))
REPORT_THREAD_ID = int(os.getenv("REPORT_THREAD_ID", 0))
DB_PATH = "data/anon_bot.db"
