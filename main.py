import asyncio
import logging
import os
from aiogram import Bot, Dispatcher
from config import BOT_TOKEN
from handlers import setup_handlers, commands
from middlewares.media_group import MediaGroupMiddleware


def startup_cleanup():
    """Clean up temp directory on startup."""
    temp_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "temp")
    if os.path.exists(temp_dir):
        print(f"Cleaning up temp directory: {temp_dir}")
        for f in os.listdir(temp_dir):
            try:
                os.remove(os.path.join(temp_dir, f))
            except Exception as e:
                print(f"Error removing {f}: {e}")
    else:
        os.makedirs(temp_dir)


async def main():
    logging.basicConfig(level=logging.INFO)
    startup_cleanup()

    if not BOT_TOKEN:
        print("Please set BOT_TOKEN environment variable in .env file")
        return

    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher()

    # Setup handlers
    dp.include_router(setup_handlers())
    dp.message.middleware(MediaGroupMiddleware())

    # Register commands in menu
    await commands.set_commands(bot)

    # Startup
    print("Bot started...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
