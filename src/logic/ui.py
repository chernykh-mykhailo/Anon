from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from l10n import l10n


def get_confirm_kb(lang: str, is_regen: bool = False) -> InlineKeyboardMarkup:
    """Standard confirmation keyboard for media/voice."""
    buttons = [
        [
            InlineKeyboardButton(
                text=l10n.format_value("button.confirm_send", lang),
                callback_data="confirm_media_send",
            ),
            InlineKeyboardButton(
                text=l10n.format_value("button.confirm_cancel", lang),
                callback_data="confirm_media_cancel",
            ),
        ]
    ]
    if is_regen:
        buttons.append(
            [
                InlineKeyboardButton(
                    text=l10n.format_value("button.confirm_regenerate", lang),
                    callback_data="confirm_media_regen",
                )
            ]
        )
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_session_stop_kb(lang: str) -> InlineKeyboardMarkup:
    """Keyboard to stop the current writing session."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=l10n.format_value("button.stop_writing", lang),
                    callback_data="stop_writing",
                )
            ]
        ]
    )


def get_settings_keyboard(lang: str, settings: dict) -> InlineKeyboardMarkup:
    """Generate the settings menu keyboard."""

    # Text labels with toggles
    msg_status = "✅" if settings.get("receive_messages", 1) else "❌"
    media_status = "✅" if settings.get("receive_media", 1) else "❌"
    auto_status = "✅" if settings.get("auto_voice", 0) else "❌"

    # Simplified voice label
    voice = settings.get("voice_gender", "rnd")
    if voice == "m":
        voice_label = "Male" if lang == "en" else "Чоловічий"
    elif voice == "f":
        voice_label = "Female" if lang == "en" else "Жіночий"
    elif voice == "rnd":
        voice_label = "Random" if lang == "en" else "Випадковий"
    else:
        voice_label = f"Code: {voice}"

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
                )
            ],
            [
                InlineKeyboardButton(
                    text=f"{l10n.format_value('settings_anon_audio', lang)} {'✅' if settings.get('anon_audio') else '❌'}",
                    callback_data="set_toggle_anon_audio",
                )
            ],
            [
                InlineKeyboardButton(
                    text=f"{l10n.format_value('settings_skip_confirm_voice', lang)} {'✅' if settings.get('skip_confirm_voice') else '❌'}",
                    callback_data="set_toggle_skip_confirm_voice",
                ),
                InlineKeyboardButton(
                    text=f"{l10n.format_value('settings_skip_confirm_media', lang)} {'✅' if settings.get('skip_confirm_media') else '❌'}",
                    callback_data="set_toggle_skip_confirm_media",
                ),
            ],
        ]
    )
    return kb
