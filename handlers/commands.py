from aiogram import Router, Bot, F
from aiogram.filters import CommandStart, CommandObject, Command, or_f
from aiogram.types import (
    Message,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    BotCommand,
    BotCommandScopeDefault,
)
from aiogram.fsm.context import FSMContext

from l10n import l10n
from database import db
from states import Form
from utils import get_lang, get_user_link

router = Router()


async def set_commands(bot):
    uk_commands = [
        BotCommand(
            command="start", description=l10n.format_value("commands.start", "uk")
        ),
        BotCommand(
            command="link", description=l10n.format_value("commands.link", "uk")
        ),
        BotCommand(
            command="lang", description=l10n.format_value("commands.lang", "uk")
        ),
        BotCommand(
            command="voice", description=l10n.format_value("commands.voice", "uk")
        ),
        BotCommand(
            command="voice_m", description=l10n.format_value("commands.voice_m", "uk")
        ),
        BotCommand(
            command="voice_f", description=l10n.format_value("commands.voice_f", "uk")
        ),
        BotCommand(
            command="voice_j", description=l10n.format_value("commands.voice_j", "uk")
        ),
        BotCommand(
            command="block", description="Заблокувати відправника (тільки реплаєм)"
        ),
        BotCommand(command="report", description="Поскаржитись (тільки реплаєм)"),
        BotCommand(command="blocked", description="Список заблокованих"),
        BotCommand(
            command="unblock", description="Розблокувати (реплаєм або /unblock ID)"
        ),
        BotCommand(
            command="donate", description=l10n.format_value("commands.donate", "uk")
        ),
    ]
    en_commands = [
        BotCommand(
            command="start", description=l10n.format_value("commands.start", "en")
        ),
        BotCommand(
            command="link", description=l10n.format_value("commands.link", "en")
        ),
        BotCommand(
            command="lang", description=l10n.format_value("commands.lang", "en")
        ),
        BotCommand(
            command="voice", description=l10n.format_value("commands.voice", "en")
        ),
        BotCommand(
            command="voice_m", description=l10n.format_value("commands.voice_m", "en")
        ),
        BotCommand(
            command="voice_f", description=l10n.format_value("commands.voice_f", "en")
        ),
        BotCommand(
            command="voice_j", description=l10n.format_value("commands.voice_j", "en")
        ),
        BotCommand(command="block", description="Block sender (reply only)"),
        BotCommand(command="report", description="Report sender (reply only)"),
        BotCommand(command="blocked", description="Blocked list"),
        BotCommand(command="unblock", description="Unblock (reply or /unblock ID)"),
        BotCommand(
            command="donate", description=l10n.format_value("commands.donate", "en")
        ),
    ]

    await bot.set_my_commands(
        uk_commands, scope=BotCommandScopeDefault(), language_code="uk"
    )
    await bot.set_my_commands(
        en_commands, scope=BotCommandScopeDefault(), language_code="en"
    )
    await bot.set_my_commands(uk_commands, scope=BotCommandScopeDefault())


@router.message(CommandStart())
async def cmd_start(message: Message, command: CommandObject, state: FSMContext, bot):
    args = command.args
    lang = await get_lang(message.from_user.id, message)

    if args:
        # Jump to message deep link: /start show_123
        if args.startswith("show_"):
            try:
                msg_to_show = int(args.split("_")[1])
                return await message.answer(
                    l10n.format_value("jump_to_message", lang),
                    reply_to_message_id=msg_to_show,
                )
            except Exception:
                pass  # Continue to user link logic if it was not a valid show_ link

        try:
            target_id = int(args)
            if target_id == message.from_user.id:
                return await message.answer(
                    l10n.format_value("error.self_message", lang)
                )

            await state.update_data(target_id=target_id)
            await state.set_state(Form.writing_message)
            await message.answer(l10n.format_value("writing_to", lang))
        except ValueError:
            await message.answer(l10n.format_value("error.invalid_link", lang))
    else:
        # Generate link
        link = (
            f"https://t.me/{(await bot.get_me()).username}?start={message.from_user.id}"
        )
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=l10n.format_value("button.get_link", lang),
                        callback_data="my_link",
                    )
                ],
            ]
        )
        await message.answer(
            l10n.format_value("welcome", lang),
            reply_markup=kb,
            parse_mode="HTML",
            disable_web_page_preview=True,
        )


@router.message(Command("link"))
async def cmd_link(message: Message, state: FSMContext, bot):
    await state.clear()
    lang = await get_lang(message.from_user.id, message)
    bot_info = await bot.get_me()
    user_link = await get_user_link(bot_info, message.from_user.id)
    await message.answer(
        l10n.format_value("your_link", lang, link=user_link),
        parse_mode="HTML",
        disable_web_page_preview=True,
    )


@router.message(Command("lang"))
async def cmd_lang(message: Message, state: FSMContext):
    await state.clear()
    lang = await get_lang(message.from_user.id, message)
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=l10n.format_value("button.lang_uk", lang),
                    callback_data="set_lang_uk",
                ),
                InlineKeyboardButton(
                    text=l10n.format_value("button.lang_en", lang),
                    callback_data="set_lang_en",
                ),
            ]
        ]
    )
    await message.answer(l10n.format_value("select_lang", lang), reply_markup=kb)


@router.message(Command("block"))
async def cmd_block(message: Message):
    lang = await get_lang(message.from_user.id, message)
    if not message.reply_to_message:
        return await message.answer(l10n.format_value("error.no_reply_target", lang))

    link = db.get_link_by_receiver(message.reply_to_message.message_id, message.chat.id)
    if not link:
        return await message.answer(l10n.format_value("error.no_reply_target", lang))

    sender_id, _, _ = link
    db.block_user(
        message.from_user.id,
        sender_id,
        reason_msg_id=message.reply_to_message.message_id,
    )
    await message.reply(l10n.format_value("user_blocked", lang))


@router.message(Command("unblock"))
async def cmd_unblock(message: Message, command: CommandObject):
    lang = await get_lang(message.from_user.id, message)

    # Mode 1: Reply to message
    if message.reply_to_message:
        link = db.get_link_by_receiver(
            message.reply_to_message.message_id, message.chat.id
        )
        if not link:
            return await message.answer(
                l10n.format_value("error.no_sender_found", lang)
            )

        sender_id, _, _ = link
        if db.unblock_user(message.from_user.id, sender_id):
            return await message.answer(l10n.format_value("user_unblocked", lang))
        else:
            return await message.answer("ℹ️ Цей користувач не був заблокований.")

    # Mode 2: By index (/unblock 1)
    args = command.args
    if args and args.isdigit():
        index = int(args)
        if db.unblock_by_index(message.from_user.id, index):
            return await message.answer(l10n.format_value("user_unblocked", lang))
        else:
            return await message.answer("❌ Некоректний ID зі списку.")

    await message.answer(
        "❓ Вкажи ID зі списку (наприклад: <code>/unblock 1</code>) або дай відповідь на повідомлення.",
        parse_mode="HTML",
    )


@router.message(Command("blocked"))
async def cmd_blocked(message: Message, bot: Bot):
    lang = await get_lang(message.from_user.id, message)
    blocked_list = db.get_blocked_list(message.from_user.id)

    if not blocked_list:
        return await message.answer(l10n.format_value("blocked_list_empty", lang))

    text = l10n.format_value("blocked_list_title", lang)
    bot_info = await bot.get_me()

    for i, (sender_id, blocked_at, msg_id) in enumerate(blocked_list, 1):
        # Format date (SQLite usually stores as YYYY-MM-DD HH:MM:SS)
        date_str = blocked_at.split(".")[0] if "." in blocked_at else blocked_at

        # Determine the correct link format
        if message.chat.type == "private":
            # Deep link to message within the bot: /start show_{msg_id}
            # This is the most robust way for private chats
            msg_link = f"https://t.me/{bot_info.username}?start=show_{msg_id}"
        else:
            # For supergroups, t.me/c/ is the standard
            chat_id_clean = str(message.chat.id).replace("-100", "")
            msg_link = f"https://t.me/c/{chat_id_clean}/{msg_id}"

        text += l10n.format_value(
            "blocked_list_item", lang, index=i, date=date_str, link=msg_link
        )

    await message.answer(text, parse_mode="HTML", disable_web_page_preview=True)


@router.message(Command("report"))
async def cmd_report(message: Message, bot: Bot):
    lang = await get_lang(message.from_user.id, message)
    if not message.reply_to_message:
        return await message.answer(l10n.format_value("error.no_reply_target", lang))

    link = db.get_link_by_receiver(message.reply_to_message.message_id, message.chat.id)
    if not link:
        return await message.answer(l10n.format_value("error.no_sender_found", lang))

    sender_id, _, _ = link
    from config import ADMIN_ID, REPORT_CHAT_ID, REPORT_THREAD_ID

    # Clickable profile links
    spammer_info = f"<a href='tg://user?id={sender_id}'>{sender_id}</a>"
    reporter_info = (
        f"<a href='tg://user?id={message.from_user.id}'>{message.from_user.id}</a>"
    )

    report_text = (
        f"🚩 <b>НОВИЙ РЕПОРТ</b>\n\n"
        f"👤 <b>Хто поскаржився:</b> {reporter_info} (ID: <code>{message.from_user.id}</code>)\n"
        f"🚫 <b>На кого:</b> {spammer_info} (ID: <code>{sender_id}</code>)\n"
        f"---"
    )

    try:
        target_chat = REPORT_CHAT_ID or ADMIN_ID
        if target_chat:
            await bot.send_message(
                target_chat,
                report_text,
                message_thread_id=REPORT_THREAD_ID if REPORT_THREAD_ID else None,
                parse_mode="HTML",
            )
            await message.reply_to_message.forward(
                target_chat,
                message_thread_id=REPORT_THREAD_ID if REPORT_THREAD_ID else None,
            )
    except Exception as e:
        print(f"Error sending report: {e}")

    await message.reply(l10n.format_value("report_sent", lang))


@router.message(Command("setlog"))
async def cmd_setlog(message: Message):
    from config import ADMIN_ID

    # Only admin can use this
    if str(message.from_user.id) != str(ADMIN_ID):
        return

    chat_id = message.chat.id
    thread_id = message.message_thread_id

    # We update the .env file dynamically
    try:
        import os

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

        # Also update current runtime config
        import config

        config.REPORT_CHAT_ID = chat_id
        config.REPORT_THREAD_ID = thread_id

        thread_info = f" (thread: {thread_id})" if thread_id else ""
        await message.answer(
            f"✅ Логи активовано для цього чату: <code>{chat_id}</code>{thread_info}\n\n<i>Зміни збережено в .env. Бот тепер шле сюди репорти.</i>",
            parse_mode="HTML",
        )
    except Exception as e:
        await message.answer(f"❌ Помилка при збереженні: {e}")


@router.message(or_f(Command("donate"), F.text.lower().in_(["донат", "donate"])))
async def cmd_donate(message: Message):
    lang = await get_lang(message.from_user.id, message)
    await message.answer(l10n.format_value("donate_text", lang), parse_mode="HTML")


@router.message(or_f(Command("admin"), F.text.lower().in_(["статистика", "stats"])))
async def cmd_admin(message: Message):
    from config import ADMIN_ID

    if str(message.from_user.id) != str(ADMIN_ID):
        return

    stats = db.get_admin_stats()

    langs_info = "\n".join(
        [
            f"— {lang.upper()}: <code>{count}</code>"
            for lang, count in stats["langs"].items()
        ]
    )

    text = (
        f"📊 <b>АДМІН-ПАНЕЛЬ СТАТИСТИКИ</b>\n\n"
        f"✉️ <b>Повідомлення:</b>\n"
        f"— Всього: <code>{stats['msg_total']}</code>\n\n"
        f"👥 <b>Користувачі:</b>\n"
        f"— Всього: <code>{stats['total_users']}</code>\n"
        f"{langs_info}\n\n"
        f"🚫 <b>Блокування:</b>\n"
        f"— Всього: <code>{stats['total_blocks']}</code>"
    )
    await message.answer(text, parse_mode="HTML")
