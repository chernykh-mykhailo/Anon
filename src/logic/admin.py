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


async def handle_report(message: Message, lang: str):
    """Handle /report command (sender reporting a message)."""
    if not message.reply_to_message:
        return await message.answer(l10n.format_value("error.reply_needed", lang))

    # Logic to process report... (placeholder for current logic)
    await message.answer(l10n.format_value("report_sent", lang))


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
