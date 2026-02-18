from aiogram import Router, Bot, F
from aiogram.filters import Command, or_f, CommandObject
from aiogram.types import (
    Message,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    BotCommand,
    BotCommandScopeDefault,
)
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile
import edge_tts

from l10n import l10n
from database import db
from states import Form
from utils import get_lang, get_user_link
from services.image_engine import cleanup_image

router = Router()


async def set_commands(bot):
    uk_commands = [
        BotCommand(
            command="start", description=l10n.format_value("commands.start", "uk")
        ),
        BotCommand(
            command="link", description=l10n.format_value("commands.link", "uk")
        ),
        BotCommand(command="help", description="Допомога та інструкції"),
        BotCommand(
            command="lang", description=l10n.format_value("commands.lang", "uk")
        ),
        BotCommand(command="pic", description=l10n.format_value("commands.pic", "uk")),
        BotCommand(
            command="voice", description=l10n.format_value("commands.voice", "uk")
        ),
        BotCommand(
            command="block", description=l10n.format_value("commands.block", "uk")
        ),
        BotCommand(
            command="report", description=l10n.format_value("commands.report", "uk")
        ),
        BotCommand(
            command="blocked", description=l10n.format_value("commands.blocked", "uk")
        ),
        BotCommand(
            command="unblock", description=l10n.format_value("commands.unblock", "uk")
        ),
        BotCommand(
            command="donate", description=l10n.format_value("commands.donate", "uk")
        ),
        BotCommand(
            command="settings", description=l10n.format_value("commands.settings", "uk")
        ),
        BotCommand(
            command="text", description=l10n.format_value("commands.text", "uk")
        ),
        BotCommand(
            command="cancel",
            description=l10n.format_value("commands.cancel", "uk")
            if l10n.format_value("commands.cancel", "uk") != "commands.cancel"
            else "Скасувати",
        ),
    ]
    en_commands = [
        BotCommand(
            command="start", description=l10n.format_value("commands.start", "en")
        ),
        BotCommand(
            command="link", description=l10n.format_value("commands.link", "en")
        ),
        BotCommand(command="help", description="Help and instructions"),
        BotCommand(
            command="lang", description=l10n.format_value("commands.lang", "en")
        ),
        BotCommand(command="pic", description=l10n.format_value("commands.pic", "en")),
        BotCommand(
            command="voice", description=l10n.format_value("commands.voice", "en")
        ),
        BotCommand(
            command="block", description=l10n.format_value("commands.block", "en")
        ),
        BotCommand(
            command="report", description=l10n.format_value("commands.report", "en")
        ),
        BotCommand(
            command="blocked", description=l10n.format_value("commands.blocked", "en")
        ),
        BotCommand(
            command="unblock", description=l10n.format_value("commands.unblock", "en")
        ),
        BotCommand(
            command="donate", description=l10n.format_value("commands.donate", "en")
        ),
        BotCommand(
            command="settings", description=l10n.format_value("commands.settings", "en")
        ),
        BotCommand(
            command="text", description=l10n.format_value("commands.text", "en")
        ),
        BotCommand(
            command="cancel",
            description=l10n.format_value("commands.cancel", "en")
            if l10n.format_value("commands.cancel", "en") != "commands.cancel"
            else "Cancel",
        ),
    ]

    await bot.set_my_commands(
        uk_commands, scope=BotCommandScopeDefault(), language_code="uk"
    )
    await bot.set_my_commands(
        en_commands, scope=BotCommandScopeDefault(), language_code="en"
    )
    await bot.set_my_commands(uk_commands, scope=BotCommandScopeDefault())


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext):
    data = await state.get_data()
    # Cleanup possible temp images
    if "current_preview_path" in data:
        cleanup_image(data["current_preview_path"])
    if "draw_settings" in data and data["draw_settings"].get("custom_bg_path"):
        cleanup_image(data["draw_settings"]["custom_bg_path"])

    await state.clear()

    lang = await get_lang(message.from_user.id, message)
    await message.answer(l10n.format_value("action_cancelled", lang))


@router.message(or_f(Command("admin"), F.text.lower().in_(["статистика", "stats"])))
async def cmd_admin(message: Message):
    from config import ADMIN_ID

    if str(message.from_user.id) != str(ADMIN_ID):
        return

    stats = db.get_admin_stats()
    current_cd = db.get_global_config("message_cooldown", "0")

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
        f"— Всього: <code>{stats['total_blocks']}</code>\n\n"
        f"⏱️ <b>Затримка (CD):</b> <code>{current_cd} сек.</code>"
    )

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="⏱️ Встановити КД", callback_data="admin_set_cooldown"
                )
            ]
        ]
    )
    await message.answer(text, parse_mode="HTML", reply_markup=kb)


@router.message(Command("start"))
@router.message(Command("help"))
async def cmd_start(
    message: Message, state: FSMContext, bot: Bot, command: CommandObject = None
):
    args = command.args if command else None
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

            await state.update_data(
                target_id=target_id,
                reply_to_id=None,
                anon_num=db.get_available_anon_num(target_id, message.from_user.id),
            )
            await state.set_state(Form.writing_message)
            # When clicking a link, the sender knows who they are writing to.
            # We show and save the name.
            target_name = "Anonymous"
            try:
                target_chat = await bot.get_chat(target_id)
                full_name = target_chat.full_name
                username = target_chat.username
                target_name = full_name  # Save for confirmation messages

                name_display = f"{full_name} (@{username})" if username else full_name
                name_link = f'<a href="tg://user?id={target_id}">{name_display}</a>'

                await state.update_data(target_name=target_name)
                data = await state.get_data()
                await message.answer(
                    l10n.format_value("writing_to_user", lang, name=name_link),
                    parse_mode="HTML",
                )
            except Exception:
                # Fallback if chat info cannot be fetched
                state_data = await state.get_data()
                anon_num_target = state_data.get("anon_num") or "№???"
                await message.answer(
                    l10n.format_value(
                        "writing_to_user", lang, name=f"<b>{anon_num_target}</b>"
                    ),
                    parse_mode="HTML",
                )
        except ValueError:
            await message.answer(l10n.format_value("error.invalid_link", lang))
    else:
        # Display standard welcome
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

    sender_id, _, _, _ = link
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

        sender_id, _, _, _ = link
        if db.unblock_user(message.from_user.id, sender_id):
            return await message.answer(l10n.format_value("user_unblocked", lang))
        else:
            return await message.answer(
                l10n.format_value("error.unblock_not_blocked", lang)
            )

    # Mode 2: By index (/unblock 1)
    args = command.args
    if args and args.isdigit():
        index = int(args)
        if db.unblock_by_index(message.from_user.id, index):
            return await message.answer(l10n.format_value("user_unblocked", lang))
        else:
            return await message.answer(
                l10n.format_value("error.unblock_invalid_id", lang)
            )

    await message.answer(
        l10n.format_value("error.unblock_instruction", lang),
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

    sender_id, _, _, _ = link
    from config import ADMIN_ID, REPORT_CHAT_ID, REPORT_THREAD_ID

    # Fetch more info for better reporting
    async def get_user_display(uid):
        try:
            c = await bot.get_chat(uid)
            name = c.full_name
            link = f"<a href='tg://user?id={uid}'>{name}</a>"
            if c.username:
                link += f" (@{c.username})"
            return link
        except Exception:
            return f"<a href='tg://user?id={uid}'>{uid}</a>"

    spammer_display = await get_user_display(sender_id)
    reporter_display = await get_user_display(message.from_user.id)

    report_text = (
        f"🚩 <b>НОВИЙ РЕПОРТ</b>\n\n"
        f"👤 <b>Хто поскаржився:</b> {reporter_display} (ID: <code>{message.from_user.id}</code>)\n"
        f"🚫 <b>На кого:</b> {spammer_display} (ID: <code>{sender_id}</code>)\n"
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

    print(f"DEBUG: cmd_setlog called by {message.from_user.id}, ADMIN_ID is {ADMIN_ID}")

    # Only admin can use this
    if str(message.from_user.id) != str(ADMIN_ID):
        return await message.answer("У вас немає прав 🤡")

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
        lang = await get_lang(message.from_user.id, message)

        await message.answer(
            l10n.format_value(
                "admin.log_activated", lang, chat_id=chat_id, thread_info=thread_info
            ),
            parse_mode="HTML",
        )
    except Exception as e:
        lang = await get_lang(message.from_user.id, message)
        await message.answer(f"❌ Error saving config: {e}")


@router.message(or_f(Command("donate"), F.text.lower().in_(["донат", "donate"])))
async def cmd_donate(message: Message):
    lang = await get_lang(message.from_user.id, message)
    await message.answer(l10n.format_value("donate_text", lang), parse_mode="HTML")


def get_settings_keyboard(lang, settings):
    on = "✅"
    off = "❌"

    msg_status = on if settings["receive_messages"] else off
    media_status = on if settings["receive_media"] else off
    auto_status = on if settings["auto_voice"] else off

    voice_char = settings["voice_gender"]
    voice_label = l10n.format_value(f"voice_{voice_char}_short", lang)

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"{l10n.format_value('settings_messages', lang)} {msg_status}",
                    callback_data="set_toggle_messages",
                )
            ],
            [
                InlineKeyboardButton(
                    text=f"{l10n.format_value('settings_media', lang)} {media_status}",
                    callback_data="set_toggle_media",
                )
            ],
            [
                InlineKeyboardButton(
                    text=f"{l10n.format_value('settings_auto_voice', lang)} {auto_status}",
                    callback_data="set_toggle_auto_voice",
                )
            ],
            [
                InlineKeyboardButton(
                    text=f"{l10n.format_value('settings_voice_gender', lang)}: {voice_label}",
                    callback_data="set_cycle_voice",
                    style="primary",
                )
            ],
            [
                InlineKeyboardButton(
                    text=f"{l10n.format_value('settings_anon_audio', lang)} {'✅' if settings['anon_audio'] else '❌'}",
                    callback_data="set_toggle_anon_audio",
                )
            ],
            [
                InlineKeyboardButton(
                    text=f"{l10n.format_value('settings_skip_confirm_voice', lang)} {'✅' if settings['skip_confirm_voice'] else '❌'}",
                    callback_data="set_toggle_skip_confirm_voice",
                    style="success" if settings["skip_confirm_voice"] else "danger",
                ),
                InlineKeyboardButton(
                    text=f"{l10n.format_value('settings_skip_confirm_media', lang)} {'✅' if settings['skip_confirm_media'] else '❌'}",
                    callback_data="set_toggle_skip_confirm_media",
                    style="success" if settings["skip_confirm_media"] else "danger",
                ),
            ],
        ]
    )
    return kb


@router.message(Command("settings"))
async def cmd_settings(message: Message):
    lang = await get_lang(message.from_user.id, message)
    settings = db.get_user_settings(message.from_user.id)
    kb = get_settings_keyboard(lang, settings)
    await message.answer(
        l10n.format_value("settings_title", lang), reply_markup=kb, parse_mode="HTML"
    )


@router.message(Command("set_voice"))
async def voice_command(message: Message, command: CommandObject):
    lang = db.get_user_lang(message.from_user.id)
    args = command.args

    if not args:
        # User wants to reset
        db.update_user_setting(message.from_user.id, "voice_gender", "m")
        text = (
            "✅ Голос скинуто до стандартного (Чоловічий)."
            if lang == "uk"
            else "✅ Voice reset to standard (Male)."
        )
        await message.answer(text, parse_mode="HTML")
        return

    voice_input = args.strip()
    voice = voice_input

    # Check if input is a number (index from /list_voices)
    if voice_input.isdigit():
        idx = int(voice_input)
        try:
            # We must fetch and sort the same way list_voices does
            import edge_tts

            all_voices = await edge_tts.list_voices()
            all_voices.sort(key=lambda x: (x["Locale"], x["ShortName"]))

            if 1 <= idx <= len(all_voices):
                voice = all_voices[idx - 1]["ShortName"]
            else:
                err = (
                    f"⚠️ Номер {idx} не знайдено. Всього голосів: {len(all_voices)}"
                    if lang == "uk"
                    else f"⚠️ Number {idx} not found. Total voices: {len(all_voices)}"
                )
                await message.answer(err, parse_mode="HTML")
                return
        except Exception as e:
            await message.answer(f"Error fetching voice list: {e}")
            return

    # Try to extract voice name if user pasted full line like "fr-FR - fr-FR-DeniseNeural (Gender: Female)"
    # We look for the part that looks like a voice code (e.g. *-*-*Neural)
    elif "Neural" in voice_input:
        # Split by common separators and find the part with "Neural"
        parts = voice_input.replace(" - ", " ").split()
        for p in parts:
            clean_p = p.strip("(),")
            if "Neural" in clean_p and "-" in clean_p:
                voice = clean_p
                break

    # Basic validation
    if "Neural" not in voice or "-" not in voice:
        err = (
            "⚠️ Некоректна назва голосу. Приклад: <code>en-US-GuyNeural</code>"
            if lang == "uk"
            else "⚠️ Invalid voice name. Example: <code>en-US-GuyNeural</code>"
        )
        await message.answer(err, parse_mode="HTML")
        return

    db.update_user_setting(message.from_user.id, "voice_gender", voice)
    msg = (
        f"✅ Голос успішно змінено на: <code>{voice}</code>"
        if lang == "uk"
        else f"✅ Voice successfully changed to: <code>{voice}</code>"
    )
    await message.answer(msg, parse_mode="HTML")


@router.message(Command("list_voices", "voice_list"))
async def list_voices_command(message: Message):
    lang = db.get_user_lang(message.from_user.id)
    wait_msg = await message.answer("⏳..." if lang == "uk" else "⏳...")

    try:
        voices = await edge_tts.list_voices()
        # Sort by locale, then name
        voices.sort(key=lambda x: (x["Locale"], x["ShortName"]))

        lines = []
        if lang == "uk":
            lines.append("Список доступних голосів (Microsoft Edge TTS):\n")
        else:
            lines.append("List of available voices (Microsoft Edge TTS):\n")

        for i, v in enumerate(voices, 1):
            try:
                # Add simplified formatting with index
                lines.append(
                    f"{i}. {v['ShortName']} (Locale: {v['Locale']}, Gender: {v['Gender']})"
                )
            except Exception:
                continue

        content = "\n".join(lines)
        file_bytes = content.encode("utf-8")

        file = BufferedInputFile(file_bytes, filename="voices.txt")
        caption = (
            "Ось повний список голосів. Використайте номер: /set_voice 117\nАбо скопіюйте код: /set_voice en-US-GuyNeural"
            if lang == "uk"
            else "Here is the full list. Use number: /set_voice 117\nOr copy code: /set_voice en-US-GuyNeural"
        )

        await message.answer_document(document=file, caption=caption)
    except Exception as e:
        await message.answer(f"Error: {e}")
    finally:
        await wait_msg.delete()
