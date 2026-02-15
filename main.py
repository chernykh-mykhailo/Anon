import asyncio
import logging
from aiogram import Bot, Dispatcher
from config import BOT_TOKEN
from handlers import setup_handlers, commands


async def main():
    logging.basicConfig(level=logging.INFO)

    if not BOT_TOKEN:
        print("Please set BOT_TOKEN environment variable in .env file")
        return

    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher()

    # Setup handlers
    dp.include_router(setup_handlers())

    # Register commands in menu
    await commands.set_commands(bot)

    # Startup
    print("Bot started...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
