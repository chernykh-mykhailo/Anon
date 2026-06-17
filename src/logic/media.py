import edge_tts
from aiogram import Bot
from aiogram.types import Message, BufferedInputFile, FSInputFile
from aiogram.fsm.context import FSMContext
from l10n import l10n
from database import db
from states import Form
from services.voice_engine import text_to_voice
from services.image_engine import generate_image_input
from logic.ui import get_confirm_kb
from logic.forwarding import handle_forwarding
from logic.session import cleanup_previous_confirmation


async def handle_voice_setting(message: Message, args: str, lang: str):
    """Process /set_voice command."""
    if not args:
        db.update_user_settings(message.from_user.id, voice_gender="m")
        text = (
            "✅ Голос скинуто до стандартного (Чоловічий)."
            if lang == "uk"
            else "✅ Voice reset to standard (Male)."
        )
        return await message.answer(text, parse_mode="HTML")

    voice_input = args.strip()
    voice = voice_input

    # 1. Handle numeric index
    if voice_input.isdigit():
        idx = int(voice_input)
        try:
            all_voices = await edge_tts.list_voices()
            all_voices.sort(key=lambda x: (x["Locale"], x["ShortName"]))
            if 1 <= idx <= len(all_voices):
                voice = all_voices[idx - 1]["ShortName"]
            else:
                err = (
                    f"⚠️ Номер {idx} не знайдено. Всього: {len(all_voices)}"
                    if lang == "uk"
                    else f"⚠️ Number {idx} not found. Total: {len(all_voices)}"
                )
                return await message.answer(err, parse_mode="HTML")
        except Exception as e:
            return await message.answer(f"Error fetching voice list: {e}")

    # 2. Extract from full line
    elif "Neural" in voice_input:
        parts = voice_input.replace(" - ", " ").split()
        for p in parts:
            clean_p = p.strip("(),")
            if "Neural" in clean_p and "-" in clean_p:
                voice = clean_p
                break

    # 3. Validation
    if "Neural" not in voice or "-" not in voice:
        err = (
            "⚠️ Некоректна назва. Приклад: <code>en-US-GuyNeural</code>"
            if lang == "uk"
            else "⚠️ Invalid name. Example: <code>en-US-GuyNeural</code>"
        )
        return await message.answer(err, parse_mode="HTML")

    db.update_user_settings(message.from_user.id, voice_gender=voice)
    msg = (
        f"✅ Голос змінено на: <code>{voice}</code>"
        if lang == "uk"
        else f"✅ Voice changed to: <code>{voice}</code>"
    )
    await message.answer(msg, parse_mode="HTML")


async def handle_list_voices(message: Message, lang: str):
    """Send voice list as a file."""
    wait_msg = await message.answer("⏳...")
    try:
        voices = await edge_tts.list_voices()
        voices.sort(key=lambda x: (x["Locale"], x["ShortName"]))

        lines = [
            "Список доступних голосів:\n"
            if lang == "uk"
            else "List of available voices:\n"
        ]
        for i, v in enumerate(voices, 1):
            lines.append(
                f"{i}. {v['ShortName']} (Locale: {v['Locale']}, Gender: {v['Gender']})"
            )

        content = "\n".join(lines).encode("utf-8")
        file = BufferedInputFile(content, filename="voices.txt")
        caption = (
            "Оберіть номер: /set_voice 117"
            if lang == "uk"
            else "Pick a number: /set_voice 117"
        )
        await message.answer_document(document=file, caption=caption)
    except Exception as e:
        await message.answer(f"Error: {e}")
    finally:
        await wait_msg.delete()


async def handle_voice_synthesis(
    message: Message,
    state: FSMContext,
    bot: Bot,
    text: str,
    target_id: int,
    reply_to_id: int,
    anon_num: str,
    lang: str,
):
    """Handle /voice execution."""
    user_settings = db.get_user_settings(message.from_user.id)
    gender = user_settings.get("voice_gender", "m")

    await message.answer(l10n.format_value("voicing_message", lang))

    try:
        voice_result = await text_to_voice(text, gender)
        path = voice_result.path

        await state.update_data(
            target_id=target_id,
            reply_to_id=reply_to_id,
            media_path=path,
            media_type="voice",
            prompt=text,
            gender=gender,
            anon_num=anon_num,
        )
        await state.set_state(Form.confirming_media)

        if user_settings.get("skip_confirm_media"):
            await cleanup_previous_confirmation(message.chat.id, state, bot)
            await handle_forwarding(
                bot,
                message,
                target_id,
                message.from_user.id,
                state,
                reply_to_id=reply_to_id,
                anon_num=anon_num,
                media_path=path,
                media_type="voice",
                check_cd=False,
            )
            return

        await message.answer_voice(
            voice=FSInputFile(path),
            caption=l10n.format_value("your_voice_preview", lang),
            reply_markup=get_confirm_kb(lang),
        )
    except Exception as e:
        await message.answer(f"Error: {e}")


async def handle_pic_generation(
    message: Message,
    state: FSMContext,
    bot: Bot,
    prompt: str,
    target_id: int,
    anon_num: str,
    lang: str,
):
    """Handle /pic execution."""
    await message.answer(l10n.format_value("generating_image", lang))

    try:
        path = await generate_image_input(prompt)

        await state.update_data(
            target_id=target_id,
            media_path=path,
            media_type="photo",
            prompt=prompt,
            anon_num=anon_num,
        )
        await state.set_state(Form.confirming_media)

        user_settings = db.get_user_settings(message.from_user.id)
        if user_settings.get("skip_confirm_media"):
            await cleanup_previous_confirmation(message.chat.id, state, bot)
            await handle_forwarding(
                bot,
                message,
                target_id,
                message.from_user.id,
                state,
                anon_num=anon_num,
                media_path=path,
                media_type="photo",
                check_cd=False,
            )
            return

        await message.answer_photo(
            photo=FSInputFile(path),
            caption=l10n.format_value("your_image_preview", lang),
            reply_markup=get_confirm_kb(lang),
        )
    except Exception as e:
        await message.answer(f"Error: {e}")
