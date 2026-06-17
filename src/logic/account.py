from aiogram import Bot
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    Message,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from aiogram.filters import CommandObject
from l10n import l10n
from database import db
from states import Form


async def handle_start_command(
    message: Message, state: FSMContext, bot: Bot, command: CommandObject, lang: str
):
    """Handle /start command with potential deep links."""
    args = command.args if command else None

    # Register new user in settings to track in stats
    if not db.get_user_lang(message.from_user.id, None):
        db.set_user_lang(message.from_user.id, lang)

    if not args:
        return await show_standard_welcome(message, lang)

    # 1. Handle "show message" links
    if args.startswith("show_"):
        return await handle_show_link(message, args, lang)

    # 2. Handle "write to user" links
    try:
        target_id = int(args)
        if target_id == message.from_user.id:
            return await message.answer(l10n.format_value("error.self_message", lang))

        anon_num = db.get_or_create_anon_num(target_id, message.from_user.id)
        await state.update_data(
            target_id=target_id, reply_to_id=None, anon_num=anon_num
        )
        await state.set_state(Form.writing_message)

        # Try to get user info for a more friendly UI
        target_name = "Anonymous"
        try:
            target_chat = await bot.get_chat(target_id)
            target_name = target_chat.full_name
            username = target_chat.username
            name_display = (
                f"{target_name} {anon_num} (@{username})"
                if username
                else f"{target_name} {anon_num}"
            )
            name_link = f'<a href="tg://user?id={target_id}">{name_display}</a>'
            await state.update_data(target_name=target_name)
            name_to_show = name_link
        except Exception:
            name_to_show = f"<b>{anon_num}</b>"

        kb_stop = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=l10n.format_value("button.stop_writing", lang),
                        callback_data="stop_writing",
                    )
                ]
            ]
        )

        await message.answer(
            l10n.format_value("writing_to_user", lang, name=name_to_show),
            parse_mode="HTML",
            reply_markup=kb_stop,
        )
    except ValueError:
        await message.answer(l10n.format_value("error.invalid_link", lang))


async def show_standard_welcome(message: Message, lang: str):
    """Show the standard bot welcome message."""
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=l10n.format_value("button.get_link", lang),
                    callback_data="my_link",
                )
            ]
        ]
    )
    await message.answer(
        l10n.format_value("welcome", lang),
        reply_markup=kb,
        parse_mode="HTML",
        disable_web_page_preview=True,
    )


async def handle_show_link(message: Message, args: str, lang: str):
    """Handle deep links like /start show_123."""
    try:
        msg_to_show = int(args.split("_")[1])
        await message.answer(
            l10n.format_value("jump_to_message", lang),
            reply_to_message_id=msg_to_show,
        )
    except (IndexError, ValueError):
        await show_standard_welcome(message, lang)
