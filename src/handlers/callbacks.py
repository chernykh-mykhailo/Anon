from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile
from typing import Union
from aiogram import Router, F, types, Bot
from aiogram.fsm.context import FSMContext

from l10n import l10n
from database import db
from states import Form
from utils import get_lang, get_user_link
from services.voice_engine import text_to_voice, cleanup_voice
from services.image_engine import generate_image_input, cleanup_image
from logic.session import cleanup_previous_confirmation
from logic.drawing import show_draw_customization
from logic.forwarding import handle_forwarding
from logic.ui import get_confirm_kb, get_settings_keyboard

router = Router()


@router.callback_query(F.data == "admin_refresh")
async def admin_refresh_callback(callback: types.CallbackQuery):
    from config import ADMIN_IDS
    from logic.admin import handle_admin_stats

    if callback.from_user.id not in ADMIN_IDS:
        return await callback.answer("У вас немає прав 🤡")

    lang = await get_lang(callback.from_user.id, callback.message)
    await handle_admin_stats(callback.message, lang, edit=True)
    await callback.answer()


@router.callback_query(F.data == "admin_set_cooldown")
async def admin_set_cooldown_callback(callback: types.CallbackQuery, state: FSMContext):
    from config import ADMIN_IDS

    if callback.from_user.id not in ADMIN_IDS:
        return await callback.answer("У вас немає прав 🤡")

    await state.set_state(Form.setting_cooldown)

    # Use localized prompt if available, or fallback
    prompt = "Введіть нове значення КД (затримки) в секундах (0 — вимкнути):"
    await callback.message.answer(prompt)
    await callback.answer()


@router.callback_query(F.data.startswith("admin_"))
async def admin_generic_callback(callback: types.CallbackQuery):
    from config import ADMIN_IDS

    if callback.from_user.id not in ADMIN_IDS:
        return await callback.answer("У вас немає прав 🤡")

    action = callback.data.replace("admin_", "")
    await callback.answer(
        f"Action '{action}' is under development 👨‍💻", show_alert=True
    )
    await callback.answer()


@router.callback_query(F.data == "my_link")
async def my_link(callback: types.CallbackQuery, bot: Bot):
    lang = await get_lang(callback.from_user.id, callback.message)
    bot_info = await bot.get_me()
    user_link = await get_user_link(bot_info, callback.from_user.id)
    await callback.message.answer(
        l10n.format_value("your_link", lang, link=user_link),
        parse_mode="HTML",
        disable_web_page_preview=True,
    )
    await callback.answer()


@router.callback_query(F.data.startswith("set_lang_"))
async def set_lang(callback: types.CallbackQuery):
    lang_code = callback.data.split("_")[-1]
    db.set_user_lang(callback.from_user.id, lang_code)
    await callback.message.edit_text(l10n.format_value("lang_changed", lang_code))
    await callback.answer()


@router.callback_query(F.data.startswith("write_to_"))
async def start_dialogue_callback(callback: types.CallbackQuery, state: FSMContext):
    """Callback to start a PERSISTENT dialogue."""
    try:
        target_id = int(callback.data.split("_")[-1])
        lang = await get_lang(callback.from_user.id, callback.message)

        # Clear stale data and set PERSISTENT target
        anon_num = db.get_or_create_anon_num(target_id, callback.from_user.id)
        await state.update_data(
            target_id=target_id,
            target_name=None,
            reply_to_id=None,
            anon_num=anon_num,
        )
        await state.set_state(Form.writing_message)

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

        await callback.message.answer(
            l10n.format_value("writing_to", lang),
            parse_mode="HTML",
            reply_markup=kb_stop,
        )
        await callback.answer()
    except Exception:
        await callback.answer()


@router.callback_query(F.data.startswith("send_again_"))
async def send_again_callback(callback: types.CallbackQuery, state: FSMContext):
    """Callback for a ONE-OFF message (Write More). Does NOT start a dialogue."""
    try:
        target_id = int(callback.data.split("_")[-1])
        lang = await get_lang(callback.from_user.id, callback.message)

        # Mark as ONE-OFF message: Use 'is_one_off' flag
        await state.update_data(
            target_id=target_id,
            reply_to_id=None,
            is_one_off=True,
            anon_num=db.get_or_create_anon_num(target_id, callback.from_user.id),
        )
        await state.set_state(Form.writing_message)

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

        await callback.message.answer(
            l10n.format_value("writing_to", lang),
            parse_mode="HTML",
            reply_markup=kb_stop,
        )
        await callback.answer()
    except Exception:
        await callback.answer()


@router.callback_query(F.data == "stop_writing")
async def stop_writing_callback(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    lang = await get_lang(callback.from_user.id, callback.message)
    await callback.message.answer(l10n.format_value("action_cancelled", lang))
    await callback.answer()


@router.callback_query(F.data.startswith("set_toggle_"))
async def toggle_setting(callback: types.CallbackQuery):
    setting_key = callback.data.replace("set_toggle_", "")
    # Map keyboard labels/data to database columns if needed
    mapping = {
        "messages": "receive_messages",
        "media": "receive_media",
        "auto_voice": "auto_voice",
        "skip_confirm_voice": "skip_confirm_voice",
        "anon_audio": "anon_audio",
        "skip_confirm_media": "skip_confirm_media",
    }
    db_column = mapping.get(setting_key)
    if not db_column:
        return await callback.answer()

    # Get current and flip
    settings = db.get_user_settings(callback.from_user.id)
    new_value = 0 if settings[db_column] else 1

    from config import ADMIN_IDS

    if callback.from_user.id in ADMIN_IDS:  # Fix for admin toggle if needed
        pass

    db.update_user_settings(callback.from_user.id, **{db_column: new_value})

    # Update keyboard
    new_settings = db.get_user_settings(callback.from_user.id)
    lang = await get_lang(callback.from_user.id, callback.message)
    await callback.message.edit_reply_markup(
        reply_markup=get_settings_keyboard(lang, new_settings)
    )
    await callback.answer()


@router.callback_query(F.data == "set_cycle_voice")
async def cycle_voice(callback: types.CallbackQuery):

    settings = db.get_user_settings(callback.from_user.id)
    current = settings.get("voice_gender", "m")

    voices = ["m", "f", "j", "r", "jenny", "ryan", "ava", "andrew", "rnd"]
    try:
        idx = voices.index(current)
        next_voice = voices[(idx + 1) % len(voices)]
    except ValueError:
        next_voice = "m"

    db.update_user_setting(callback.from_user.id, "voice_gender", next_voice)

    # Update keyboard
    new_settings = db.get_user_settings(callback.from_user.id)
    lang = await get_lang(callback.from_user.id, callback.message)
    await callback.message.edit_reply_markup(
        reply_markup=get_settings_keyboard(lang, new_settings)
    )
    await callback.answer()


@router.callback_query(Form.confirming_media, F.data == "confirm_media_cancel")
async def confirm_media_cancel(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    media_path = data.get("media_path")
    media_type = data.get("media_type")

    if media_path:
        if media_type in ["voice", "video_note", "video"]:
            await cleanup_voice(media_path)
        else:
            cleanup_image(media_path)

    await state.clear()
    await callback.message.delete()
    await callback.answer()


@router.callback_query(Form.confirming_media, F.data == "confirm_media_send")
async def confirm_media_send(
    callback: Union[types.CallbackQuery, any],
    state: FSMContext,
    bot: Bot,
    check_cd: bool = True,
):
    data = await state.get_data()
    target_id = data.get("target_id")
    media_path = data.get("media_path")
    media_type = data.get("media_type")

    if not target_id or not media_path:
        lang = db.get_user_lang(callback.from_user.id)
        return await callback.answer(
            l10n.format_value("error.data_missing", lang), show_alert=True
        )

    await cleanup_previous_confirmation(callback.message.chat.id, state, bot)

    await handle_forwarding(
        bot,
        callback.message,
        target_id,
        callback.from_user.id,
        state,
        reply_to_id=data.get("reply_to_id"),
        anon_num=data.get("anon_num"),
        media_path=media_path,
        media_type=media_type,
        check_cd=check_cd,
    )

    await callback.answer()


@router.callback_query(Form.confirming_media, F.data == "confirm_original_send")
async def confirm_original_send(
    callback: types.CallbackQuery, state: FSMContext, bot: Bot
):
    data = await state.get_data()
    target_id = data.get("target_id")
    orig_msg_id = data.get("original_message_id")
    media_path = data.get("media_path")

    if not target_id or not orig_msg_id:
        lang = db.get_user_lang(callback.from_user.id)
        return await callback.answer(
            l10n.format_value("error.data_missing", lang), show_alert=True
        )

    await cleanup_previous_confirmation(callback.message.chat.id, state, bot)

    await handle_forwarding(
        bot,
        callback.message,
        target_id,
        callback.from_user.id,
        state,
        reply_to_id=data.get("reply_to_id"),
        anon_num=data.get("anon_num"),
    )

    # Cleanup the anonymized preview file if it exists
    if media_path:
        await cleanup_voice(media_path)

    await callback.answer()


@router.callback_query(Form.confirming_media, F.data == "confirm_media_regen")
async def confirm_media_regen(
    callback: types.CallbackQuery, state: FSMContext, bot: Bot
):
    data = await state.get_data()
    media_type = data.get("media_type")
    media_path = data.get("media_path")
    prompt = data.get("prompt")
    gender = data.get("gender")
    lang = await get_lang(callback.from_user.id, callback.message)

    # Cleanup old
    if media_path:
        if media_type == "voice":
            cleanup_voice(media_path)
        else:
            cleanup_image(media_path)

    await callback.answer(
        l10n.format_value(
            "voicing_message" if media_type == "voice" else "generating_image", lang
        )
    )

    try:
        if media_type == "voice":
            new_voice = await text_to_voice(prompt, gender)
            new_path = new_voice.path
            # Update preview
            await callback.message.edit_media(
                media=types.InputMediaVoice(media=FSInputFile(new_path)),
                reply_markup=callback.message.reply_markup,
            )
        else:
            new_path = await generate_image_input(prompt)
            # Update preview
            await callback.message.edit_media(
                media=types.InputMediaPhoto(media=FSInputFile(new_path)),
                reply_markup=callback.message.reply_markup,
            )

        await state.update_data(media_path=new_path)
    except Exception as e:
        print(f"Error regenerating: {e}")
        await callback.answer(
            l10n.format_value("error.regen_failed", lang), show_alert=True
        )


@router.callback_query(Form.customizing_draw, F.data.startswith("draw_"))
async def process_draw_callback(
    callback: types.CallbackQuery, state: FSMContext, bot: Bot
):
    # Using top-level import logic.drawing.show_draw_customization

    lang = await get_lang(callback.from_user.id, callback.message)
    data = await state.get_data()
    s = data.get("draw_settings")

    if not s:
        await callback.answer(
            l10n.format_value("error.session_expired", lang), show_alert=True
        )
        return

    action = callback.data.replace("draw_", "")

    if action == "apply":
        # Transition to confirm_media flow
        target_id = s["target_id"]
        media_path = data.get("current_preview_path")
        media_type = "photo"  # Drawing results are photos
        prompt = s["text"]

        await state.update_data(
            target_id=target_id,
            media_path=media_path,
            media_type=media_type,
            prompt=prompt,
        )
        await state.set_state(Form.confirming_media)

        # CHECK QUICK SEND SETTING
        user_settings = db.get_user_settings(callback.from_user.id)
        if user_settings.get("skip_confirm_media"):
            await confirm_media_send(callback, state, bot, check_cd=False)
            return

        # Regular confirmation flow
        await callback.message.edit_caption(
            caption=l10n.format_value("your_image_preview", lang),
            reply_markup=get_confirm_kb(lang),
        )
        await callback.answer()
        return

    # Handle customization buttons (rest unchanged)
    if action.startswith("pos_"):
        s["y_position"] = action.replace("pos_", "")
    elif action.startswith("color_"):
        s["text_color"] = action.replace("color_", "")
    elif action == "toggle_bg":
        s["use_bg"] = not s.get("use_bg", True)

    await state.update_data(draw_settings=s)
    await show_draw_customization(callback, state, bot, lang)
    await callback.answer()
