from aiogram import Router, Bot
from aiogram.filters import Command, or_f, CommandObject
from aiogram.types import Message, BotCommand, BotCommandScopeDefault
from aiogram.fsm.context import FSMContext

from l10n import l10n
from database import db
from config import ADMIN_IDS
from utils import get_lang, get_user_link
from logic.ui import get_settings_keyboard
from logic.account import handle_start_command
from logic.admin import handle_report, handle_admin_stats
from logic.media import handle_voice_setting, handle_list_voices

router = Router()


async def set_commands(bot: Bot):
    """Register bot commands in Telegram."""
    for lang_code in ["uk", "en"]:
        cmds = [
            BotCommand(
                command="start",
                description=l10n.format_value("commands.start", lang_code),
            ),
            BotCommand(
                command="link",
                description=l10n.format_value("commands.link", lang_code),
            ),
            BotCommand(
                command="lang",
                description=l10n.format_value("commands.lang", lang_code),
            ),
            BotCommand(
                command="pic", description=l10n.format_value("commands.pic", lang_code)
            ),
            BotCommand(
                command="voice",
                description=l10n.format_value("commands.voice", lang_code),
            ),
            BotCommand(
                command="block",
                description=l10n.format_value("commands.block", lang_code),
            ),
            BotCommand(
                command="report",
                description=l10n.format_value("commands.report", lang_code),
            ),
            BotCommand(
                command="blocked",
                description=l10n.format_value("commands.blocked", lang_code),
            ),
            BotCommand(
                command="unblock",
                description=l10n.format_value("commands.unblock", lang_code),
            ),
            BotCommand(
                command="settings",
                description=l10n.format_value("commands.settings", lang_code),
            ),
            BotCommand(
                command="cancel",
                description="Скасувати" if lang_code == "uk" else "Cancel",
            ),
        ]
        await bot.set_my_commands(
            cmds, scope=BotCommandScopeDefault(), language_code=lang_code
        )


@router.message(or_f(Command("start"), Command("help")))
async def cmd_start_handler(
    message: Message, state: FSMContext, bot: Bot, command: CommandObject = None
):
    lang = await get_lang(message.from_user.id, message)
    await handle_start_command(message, state, bot, command, lang)


@router.message(Command("link"))
async def cmd_link(message: Message, bot: Bot):
    lang = await get_lang(message.from_user.id, message)
    bot_info = await bot.get_me()
    link = await get_user_link(bot_info, message.from_user.id)
    await message.answer(
        l10n.format_value("your_link", lang, link=link),
        parse_mode="HTML",
        disable_web_page_preview=True,
    )


@router.message(Command("settings"))
async def cmd_settings(message: Message):
    lang = await get_lang(message.from_user.id, message)
    settings = db.get_user_settings(message.from_user.id)
    kb = get_settings_keyboard(lang, settings)
    await message.answer(
        l10n.format_value("settings_title", lang), reply_markup=kb, parse_mode="HTML"
    )


@router.message(Command("set_voice"))
async def cmd_voice_setting(message: Message, command: CommandObject):
    lang = db.get_user_lang(message.from_user.id)
    await handle_voice_setting(message, command.args, lang)


@router.message(or_f(Command("list_voices"), Command("voice_list")))
async def cmd_list_voices(message: Message):
    lang = db.get_user_lang(message.from_user.id)
    await handle_list_voices(message, lang)


@router.message(Command("report"))
async def cmd_report(message: Message, bot: Bot):
    lang = db.get_user_lang(message.from_user.id)
    await handle_report(message, bot, lang)


@router.message(Command("setlog"))
async def cmd_setlog(message: Message, bot: Bot):
    if message.from_user.id not in ADMIN_IDS:
        return await message.answer("У вас немає прав 🤡")

    chat_id = message.chat.id
    thread_id = message.message_thread_id

    # 1. Save to Database (persists across container restarts)
    db.set_global_config("report_chat_id", str(chat_id))
    db.set_global_config("report_thread_id", str(thread_id) if thread_id else "")

    # 2. Update config in runtime
    import config
    config.REPORT_CHAT_ID = chat_id
    config.REPORT_THREAD_ID = thread_id if thread_id else 0

    # 3. Update .env file
    try:
        import os
        env_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"
        )
        if not os.path.exists(env_path):
            env_path = ".env"

        lines = []
        if os.path.exists(env_path):
            with open(env_path, "r", encoding="utf-8") as f:
                lines = f.readlines()

        new_lines = []
        found_chat = False
        found_thread = False

        for line in lines:
            if line.startswith("REPORT_CHAT_ID="):
                new_lines.append(f"REPORT_CHAT_ID={chat_id}\n")
                found_chat = True
            elif line.startswith("REPORT_THREAD_ID="):
                new_lines.append(f"REPORT_THREAD_ID={thread_id if thread_id else ''}\n")
                found_thread = True
            else:
                new_lines.append(line)

        if not found_chat:
            new_lines.append(f"REPORT_CHAT_ID={chat_id}\n")
        if not found_thread and thread_id:
            new_lines.append(f"REPORT_THREAD_ID={thread_id}\n")

        with open(env_path, "w", encoding="utf-8") as f:
            f.writelines(new_lines)
    except Exception as e:
        print(f"Warning: could not update .env: {e}")

    thread_info = f" (thread: {thread_id})" if thread_id else ""
    lang = await get_lang(message.from_user.id, message)

    msg = l10n.format_value("admin.log_activated", lang, chat_id=chat_id, thread_info=thread_info)
    if not msg:
        msg = f"✅ Логи активовано для цього чату: <code>{chat_id}</code>{thread_info}\n\n<i>Зміни збережено в .env. Бот тепер шле сюди репорти та логи.</i>"
    await message.answer(msg, parse_mode="HTML")

    try:
        await bot.send_message(
            chat_id=chat_id,
            text=f"🔔 <b>Канал логів активовано!</b>\nСюди надходитимуть логи помилок та скарги (/report).",
            message_thread_id=thread_id if thread_id else None,
            parse_mode="HTML",
        )
    except Exception as e:
        await message.answer(f"⚠️ Не вдалося надіслати тестове повідомлення: {e}")


@router.message(Command("admin"))
async def cmd_admin(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    lang = db.get_user_lang(message.from_user.id)
    await handle_admin_stats(message, lang)


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext):
    await state.clear()
    lang = await get_lang(message.from_user.id, message)
    await message.answer(l10n.format_value("writing_stopped", lang) or "Скасовано.")
