import os
from dotenv import load_dotenv

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_IDS = [
    int(i.strip()) for i in os.getenv("ADMIN_IDS", "").split(",") if i.strip().isdigit()
]
# Fallback to old single ID if list is empty for backward compatibility
if not ADMIN_IDS and os.getenv("ADMIN_ID"):
    ADMIN_IDS = [int(os.getenv("ADMIN_ID"))]
REPORT_CHAT_ID = int(os.getenv("REPORT_CHAT_ID", 0))
REPORT_THREAD_ID = int(os.getenv("REPORT_THREAD_ID", 0))
DB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "anon_bot.db"
)
AZURE_SPEECH_KEY = os.getenv("AZURE_SPEECH_KEY")
AZURE_SPEECH_REGION = os.getenv("AZURE_SPEECH_REGION")
