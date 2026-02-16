from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile
from l10n import l10n
from database import db
from states import Form
from utils import get_lang, get_user_link
from voice_engine import text_to_voice, cleanup_voice
from image_engine import generate_image_input, cleanup_image

from aiogram import Router, F, types, Bot
from aiogram.fsm.context import FSMContext

router = Router()


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
async def write_to_(callback: types.CallbackQuery, state: FSMContext):
    try:
        target_id = int(callback.data.split("_")[-1])
        lang = await get_lang(callback.from_user.id, callback.message)
        await state.update_data(target_id=target_id)
        await state.set_state(Form.writing_message)
        await callback.message.answer(l10n.format_value("writing_to", lang))
        await callback.answer()
    except Exception:
        await callback.answer()


@router.callback_query(F.data.startswith("set_toggle_"))
async def toggle_setting(callback: types.CallbackQuery):
    from handlers.commands import get_settings_keyboard

    setting_key = callback.data.replace("set_toggle_", "")
    # Map keyboard labels/data to database columns if needed
    db_column = "receive_messages" if setting_key == "messages" else "receive_media"

    # Get current and flip
    settings = db.get_user_settings(callback.from_user.id)
    new_value = 0 if settings[db_column] else 1

    db.update_user_setting(callback.from_user.id, db_column, new_value)

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
        if media_type == "voice":
            cleanup_voice(media_path)
        else:
            cleanup_image(media_path)

    await state.clear()
    await callback.message.delete()
    await callback.answer()


@router.callback_query(Form.confirming_media, F.data == "confirm_media_send")
async def confirm_media_send(
    callback: types.CallbackQuery, state: FSMContext, bot: Bot
):
    data = await state.get_data()
    target_id = data.get("target_id")
    reply_to_id = data.get("reply_to_id")
    media_path = data.get("media_path")
    media_type = data.get("media_type")

    if not target_id or not media_path:
        await callback.answer("Error: data missing", show_alert=True)
        return

    lang = await get_lang(callback.from_user.id, callback.message)
    target_lang = await get_lang(target_id)

    # Notify about new message
    notify_key = "reply_received" if reply_to_id else "new_anonymous_msg"
    effect_id = "5046509860445903448"  # Party effect

    try:
        notify_text = l10n.format_value(notify_key, target_lang)
        if media_type == "voice":
            notify_text += " 🎤"
        await bot.send_message(
            target_id,
            notify_text,
            message_effect_id=effect_id,
        )
    except Exception:
        pass

    # Send media to target
    if media_type == "voice":
        sent_msg = await bot.send_voice(
            chat_id=target_id,
            voice=FSInputFile(media_path),
            reply_to_message_id=reply_to_id,
        )
        cleanup_voice(media_path)
    else:
        sent_msg = await bot.send_photo(
            chat_id=target_id,
            photo=FSInputFile(media_path),
            caption=l10n.format_value("received_card_caption", target_lang),
            parse_mode="HTML",
            has_spoiler=True,
        )
        cleanup_image(media_path)

    # Save link
    db.save_link(
        sent_msg.message_id,
        target_id,
        callback.from_user.id,
        callback.message.message_id,
        callback.message.chat.id,
    )

    # Confirm to sender
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=l10n.format_value("button.write_more", lang),
                    callback_data=f"write_to_{target_id}",
                )
            ]
        ]
    )

    if media_type == "draw":
        await callback.message.edit_caption(
            caption=l10n.format_value("msg_sent", lang), reply_markup=kb
        )
    else:
        # Voice messages might not have caption, send new message
        await callback.message.answer(
            l10n.format_value("msg_sent", lang), reply_markup=kb
        )
        await callback.message.delete()

    await state.clear()
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
        await callback.answer("Error regenerating. Try again.", show_alert=True)
