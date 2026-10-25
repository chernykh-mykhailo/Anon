from datetime import datetime
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from l10n import l10n
from database import db


def get_admin_keyboard(lang: str) -> InlineKeyboardMarkup:
    """Generate professional admin keyboard."""
    buttons = [
        [
            InlineKeyboardButton(
                text=l10n.format_value("admin_panel.btn_refresh", lang),
                callback_data="admin_refresh",
            )
        ],
        [
            InlineKeyboardButton(
                text=l10n.format_value("admin_panel.btn_broadcast", lang),
                callback_data="admin_broadcast",
            )
        ],
        [
            InlineKeyboardButton(
                text=l10n.format_value("admin_panel.btn_logs", lang),
                callback_data="admin_logs",
            ),
            InlineKeyboardButton(
                text=l10n.format_value("admin_panel.btn_settings", lang),
                callback_data="admin_settings",
            ),
        ],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


from aiogram import Bot


async def handle_report(message: Message, bot: Bot, lang: str):
    """Handle /report command (sender reporting a message)."""
    if not message.reply_to_message:
        return await message.answer(l10n.format_value("error.no_reply_target", lang) or "Цю команду треба використовувати у відповідь на повідомлення.")

    link = db.get_link_by_receiver(message.reply_to_message.message_id, message.chat.id)
    if not link:
        return await message.answer(l10n.format_value("error.no_sender_found", lang))

    sender_id, _, _, _ = link

    from config import ADMIN_IDS, REPORT_CHAT_ID, REPORT_THREAD_ID
    target_chat = (
        db.get_global_config("report_chat_id")
        or REPORT_CHAT_ID
        or (ADMIN_IDS[0] if ADMIN_IDS else None)
    )
    target_thread = db.get_global_config("report_thread_id") or REPORT_THREAD_ID or None

    async def get_user_display(uid):
        try:
            c = await bot.get_chat(uid)
            name = c.full_name
            link_html = f"<a href='tg://user?id={uid}'>{name}</a>"
            if c.username:
                link_html += f" (@{c.username})"
            return link_html
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
        if target_chat:
            target_chat_id = int(target_chat)
            thread_id = int(target_thread) if target_thread else None
            await bot.send_message(
                target_chat_id,
                report_text,
                message_thread_id=thread_id,
                parse_mode="HTML",
            )
            await message.reply_to_message.forward(
                target_chat_id,
                message_thread_id=thread_id,
            )
    except Exception as e:
        print(f"Error sending report: {e}")

    await message.reply(l10n.format_value("report_sent", lang))


async def handle_admin_stats(message: Message, lang: str, edit: bool = False):
    """Show redesigned premium admin statistics."""
    stats = db.get_admin_stats()

    # Get active sessions count (updated logic)
    with db._get_connection() as conn:
        active_sessions = conn.execute(
            "SELECT COUNT(*) FROM active_sessions WHERE updated_at > datetime('now', '-5 minutes')"
        ).fetchone()[0]

    langs_str = "\n".join(
        [
            f"  — {lang_code.upper()}: <code>{count}</code>"
            for lang_code, count in stats["langs"].items()
        ]
    )

    # Get global cooldown
    global_cd = db.get_global_config("message_cooldown", 0)

    text = l10n.format_value(
        "admin_panel.title",
        lang,
        total_users=stats["total_users"],
        msg_total=stats["msg_total"],
        total_blocks=stats["total_blocks"],
        active_sessions=active_sessions,
        global_cd=global_cd,
        langs=langs_str,
        time=datetime.now().strftime("%H:%M:%S"),
    )

    kb = get_admin_keyboard(lang)
    # Add cooldown button directly to the keyboard
    kb.inline_keyboard.insert(
        2,
        [
            InlineKeyboardButton(
                text=l10n.format_value("admin_panel.btn_cooldown", lang),
                callback_data="admin_set_cooldown",
            )
        ],
    )

    if edit:
        await message.edit_text(text, parse_mode="HTML", reply_markup=kb)
    else:
        await message.answer(text, parse_mode="HTML", reply_markup=kb)
