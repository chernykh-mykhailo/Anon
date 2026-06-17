from aiogram import Bot, Router, F
from aiogram.types import Message
from aiogram.fsm.context import FSMContext

from database import db
from l10n import l10n
from logic.session import get_active_target
from logic.forwarding import handle_forwarding
from logic.media import handle_voice_synthesis, handle_pic_generation
from logic.drawing import start_draw_flow
from states import Form
from utils import get_lang

router = Router()


@router.message(F.text.startswith("/text"))
async def process_text_command(message: Message, state: FSMContext, bot: Bot):
    lang = await get_lang(message.from_user.id, message)
    target_id, reply_to_id, anon_num = await get_active_target(message, state, bot)
    if not target_id:
        return await message.answer(l10n.format_value("error.no_target", lang))

    parts = message.text.split(maxsplit=1)
    text = parts[1] if len(parts) > 1 else None
    if not text:
        return await message.answer(l10n.format_value("error.text_instruction", lang))

    await handle_forwarding(
        bot,
        message,
        target_id,
        message.from_user.id,
        state,
        reply_to_id=reply_to_id,
        anon_num=anon_num,
        override_text=text,
    )


@router.message(F.text.startswith(("/voice", "/voice_m", "/voice_f", "/voice_j")))
async def process_voice_command(message: Message, state: FSMContext, bot: Bot):
    lang = await get_lang(message.from_user.id, message)
    target_id, reply_to_id, anon_num = await get_active_target(message, state, bot)
    if not target_id:
        return await message.answer(l10n.format_value("error.no_target", lang))

    parts = message.text.split(maxsplit=1)
    text = parts[1] if len(parts) > 1 else None
    if not text and message.reply_to_message:
        text = message.reply_to_message.text or message.reply_to_message.caption

    if not text:
        return await message.answer(l10n.format_value("error.no_text_voice", lang))

    await handle_voice_synthesis(
        message, state, bot, text, target_id, reply_to_id, anon_num, lang
    )


@router.message(F.text.startswith("/pic"))
async def process_pic_command(message: Message, state: FSMContext, bot: Bot):
    lang = await get_lang(message.from_user.id, message)
    target_id, _, anon_num = await get_active_target(message, state, bot)
    if not target_id:
        return await message.answer(l10n.format_value("error.no_target", lang))

    parts = message.text.split(maxsplit=1)
    prompt = parts[1] if len(parts) > 1 else None
    if not prompt:
        return await message.answer(l10n.format_value("error.pic_instruction", lang))

    await handle_pic_generation(message, state, bot, prompt, target_id, anon_num, lang)


@router.message(F.text.startswith("/draw"))
async def process_draw_handler(message: Message, state: FSMContext, bot: Bot):
    lang = await get_lang(message.from_user.id, message)
    target_id, _, _ = await get_active_target(message, state, bot)
    if not target_id:
        return await message.answer(l10n.format_value("error.no_target", lang))
    await start_draw_flow(message, state, bot, target_id, lang)


@router.message(F.reply_to_message)
async def process_reply_handler(
    message: Message, bot: Bot, state: FSMContext, album: list = None
):
    target_id, reply_to_id, anon_num = await get_active_target(message, state, bot)
    if target_id:
        await handle_forwarding(
            bot,
            message,
            target_id,
            message.from_user.id,
            state,
            reply_to_id=reply_to_id,
            anon_num=anon_num,
            album=album,
        )


@router.message(Form.writing_message)
async def process_active_session(
    message: Message, state: FSMContext, bot: Bot, album: list = None
):
    if (
        not album
        and message.text
        and message.text.startswith("/")
        and not message.text.startswith("/text")
    ):
        await state.clear()
        return  # Let global command handlers deal with it

    target_id, reply_to_id, anon_num = await get_active_target(message, state, bot)
    if target_id:
        user_settings = db.get_user_settings(message.from_user.id)
        if not album and message.text and user_settings.get("auto_voice"):
            # For auto-voice, we call the handler directly with the text
            await handle_voice_synthesis(
                message,
                state,
                bot,
                message.text,
                target_id,
                reply_to_id,
                anon_num,
                await get_lang(message.from_user.id, message),
            )
        else:
            await handle_forwarding(
                bot,
                message,
                target_id,
                message.from_user.id,
                state,
                reply_to_id=reply_to_id,
                anon_num=anon_num,
                album=album,
            )

        # ONE-OFF MESSAGE REFINEMENT:
        # If this was a "Write more" (one-off) message, clear the state immediately.
        data = await state.get_data()
        if data.get("is_one_off"):
            await state.clear()


@router.message(Form.setting_cooldown)
async def process_setting_cooldown(message: Message, state: FSMContext):
    from config import ADMIN_IDS

    if message.from_user.id not in ADMIN_IDS:
        return await state.clear()

    if message.text and message.text.isdigit():
        db.set_global_config("message_cooldown", int(message.text))
        lang = db.get_user_lang(message.from_user.id)
        await message.answer(
            l10n.format_value("admin.cooldown_set", lang, seconds=message.text)
        )
        await state.clear()


@router.message()
async def process_unhandled(message: Message, state: FSMContext, bot: Bot):
    if message.chat.type != "private":
        return
    target_id, _, _ = await get_active_target(message, state, bot)
    if target_id:
        return await process_active_session(message, state, bot)

    lang = await get_lang(message.from_user.id, message)
    await message.answer(l10n.format_value("error.unknown_action", lang))
