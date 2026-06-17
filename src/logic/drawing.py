import os
from typing import Union, Optional
from aiogram import Bot, types
from aiogram.types import (
    Message,
    FSInputFile,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from aiogram.fsm.context import FSMContext
from database import db
from l10n import l10n
from states import Form
from services.image_engine import generate_image_input, cleanup_image
from utils import get_lang


async def start_draw_flow(
    message: Message, state: FSMContext, bot: Bot, target_id: int, lang: str
):
    """Initial /draw setup."""
    text = None
    photo_file_id = None

    # Base directory for temp files
    base_dir = os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    )
    temp_dir = os.path.join(base_dir, "temp")
    if not os.path.exists(temp_dir):
        os.makedirs(temp_dir)

    # 1. Reply to photo
    if message.reply_to_message and message.reply_to_message.photo:
        photo_file_id = message.reply_to_message.photo[-1].file_id
        parts = message.text.split(maxsplit=1) if message.text else []
        text = parts[1] if len(parts) > 1 else None

    # 2. Photo with caption
    elif message.photo:
        photo_file_id = message.photo[-1].file_id
        if message.caption:
            parts = message.caption.split(maxsplit=1)
            if parts[0].lower().startswith("/draw"):
                text = parts[1] if len(parts) > 1 else None
            else:
                text = message.caption

    # 3. Command with text only
    else:
        parts = message.text.split(maxsplit=1) if message.text else []
        text = parts[1] if len(parts) > 1 else None

    if not text:
        return await message.answer(l10n.format_value("error.draw_no_text", lang))

    await message.answer(l10n.format_value("drawing_wait", lang))

    custom_bg_path = None
    if photo_file_id:
        custom_bg_path = os.path.join(temp_dir, f"draw_bg_{message.from_user.id}.jpg")
        await bot.download(photo_file_id, destination=custom_bg_path)

    draw_settings = {
        "text": text,
        "custom_bg_path": custom_bg_path,
        "y_position": "center",
        "text_color": "white",
        "use_bg": True,
        "target_id": target_id,
    }

    await state.update_data(draw_settings=draw_settings)
    await state.set_state(Form.customizing_draw)
    await show_draw_customization(message, state, bot, lang, is_new=True)


async def show_draw_customization(
    message: Union[Message, types.CallbackQuery],
    state: FSMContext,
    bot: Bot,
    lang: str,
    is_new: bool = False,
):
    """The interactive Draw 2.0 menu."""
    user_id = message.from_user.id
    data = await state.get_data()
    s = data.get("draw_settings")
    if not s:
        return

    status_text = l10n.format_value("generating_image" if is_new else "editing", lang)

    # UI updates
    if not is_new and isinstance(message, types.CallbackQuery):
        await message.answer(status_text)
    else:
        wait_msg = await bot.send_message(user_id, status_text)

    try:
        file_path = await generate_image_input(
            text=s["text"],
            custom_bg_path=s["custom_bg_path"],
            y_position=s["y_position"],
            text_color_input=s["text_color"],
            use_bg=s["use_bg"],
        )

        user_settings = db.get_user_settings(user_id)
        if user_settings.get("skip_confirm_media"):
            # Auto-send logic if user enabled skip_confirm
            from logic.forwarding import handle_forwarding

            sent_pic = await bot.send_photo(
                chat_id=user_id,
                photo=FSInputFile(file_path),
                caption=l10n.format_value("msg_sent", lang),
            )
            # Cleanup
            if is_new:
                await bot.delete_message(user_id, wait_msg.message_id)
            else:
                await message.delete()

            await state.update_data(
                target_id=s["target_id"], media_path=file_path, media_type="pic"
            )
            await handle_forwarding(
                bot, sent_pic, s["target_id"], user_id, state, check_cd=True
            )
            return

        kb = get_draw_kb(s, lang)

        # Cleanup old preview
        old_path = data.get("current_preview_path")
        if old_path:
            cleanup_image(old_path)

        if is_new:
            await bot.delete_message(user_id, wait_msg.message_id)
            sent_msg = await bot.send_photo(
                chat_id=user_id,
                photo=FSInputFile(file_path),
                caption=l10n.format_value("draw_menu", lang),
                reply_markup=kb,
                parse_mode="HTML",
            )
            await state.update_data(menu_msg_id=sent_msg.message_id)
        else:
            menu_msg_id = data.get("menu_msg_id")
            if menu_msg_id:
                try:
                    await bot.edit_message_media(
                        chat_id=user_id,
                        message_id=menu_msg_id,
                        media=types.InputMediaPhoto(
                            media=FSInputFile(file_path),
                            caption=l10n.format_value("draw_menu", lang),
                            parse_mode="HTML",
                        ),
                        reply_markup=kb,
                    )
                except Exception:
                    # Fallback to new message
                    sent_msg = await bot.send_photo(
                        chat_id=user_id,
                        photo=FSInputFile(file_path),
                        caption=l10n.format_value("draw_menu", lang),
                        reply_markup=kb,
                        parse_mode="HTML",
                    )
                    await state.update_data(menu_msg_id=sent_msg.message_id)

        await state.update_data(current_preview_path=file_path)

    except Exception as e:
        print(f"Error in show_draw_customization: {e}")
        await bot.send_message(user_id, l10n.format_value("error.error_pic", lang))


def get_draw_kb(s: dict, lang: str) -> InlineKeyboardMarkup:
    """Helper to build Draw keyboard."""
    pos_text = {
        "top": l10n.format_value("button.draw_pos_top", lang),
        "center": l10n.format_value("button.draw_pos_center", lang),
        "bottom": l10n.format_value("button.draw_pos_bottom", lang),
    }
    color_text = {
        "white": l10n.format_value("button.draw_color_white", lang),
        "black": l10n.format_value("button.draw_color_black", lang),
    }
    bg_text = l10n.format_value(
        "button.draw_bg_on" if s["use_bg"] else "button.draw_bg_off", lang
    )

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=pos_text["top"], callback_data="draw_pos_top"
                ),
                InlineKeyboardButton(
                    text=pos_text["center"], callback_data="draw_pos_center"
                ),
                InlineKeyboardButton(
                    text=pos_text["bottom"], callback_data="draw_pos_bottom"
                ),
            ],
            [
                InlineKeyboardButton(
                    text=color_text["white"], callback_data="draw_color_white"
                ),
                InlineKeyboardButton(
                    text=color_text["black"], callback_data="draw_color_black"
                ),
            ],
            [InlineKeyboardButton(text=bg_text, callback_data="draw_toggle_bg")],
            [
                InlineKeyboardButton(
                    text=l10n.format_value("button.draw_apply", lang),
                    callback_data="draw_apply",
                )
            ],
        ]
    )
