from aiogram import Router, F, types, Bot
from aiogram.fsm.context import FSMContext
from l10n import l10n
from database import db
from states import Form
from utils import get_lang, get_user_link

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
