from aiogram import Router, Bot
from aiogram.filters import Command, or_f, CommandObject
from aiogram.types import Message, BotCommand, BotCommandScopeDefault
from aiogram.fsm.context import FSMContext

from l10n import l10n
from database import db
from config import ADMIN_IDS
from utils import get_lang, get_user_link
from logic.ui import get_settings_keyboard
from logic.account import handle_start_command
from logic.admin import handle_report, handle_admin_stats
from logic.media import handle_voice_setting, handle_list_voices

router = Router()


async def set_commands(bot: Bot):
    """Register bot commands in Telegram."""
    for lang_code in ["uk", "en"]:
        cmds = [
            BotCommand(
                command="start",
                description=l10n.format_value("commands.start", lang_code),
            ),
            BotCommand(
                command="link",
                description=l10n.format_value("commands.link", lang_code),
            ),
            BotCommand(
                command="lang",
                description=l10n.format_value("commands.lang", lang_code),
            ),
            BotCommand(
                command="pic", description=l10n.format_value("commands.pic", lang_code)
            ),
            BotCommand(
                command="voice",
                description=l10n.format_value("commands.voice", lang_code),
            ),
            BotCommand(
                command="block",
                description=l10n.format_value("commands.block", lang_code),
            ),
            BotCommand(
                command="report",
                description=l10n.format_value("commands.report", lang_code),
            ),
            BotCommand(
                command="blocked",
                description=l10n.format_value("commands.blocked", lang_code),
            ),
            BotCommand(
                command="unblock",
                description=l10n.format_value("commands.unblock", lang_code),
            ),
            BotCommand(
                command="settings",
                description=l10n.format_value("commands.settings", lang_code),
            ),
            BotCommand(
                command="cancel",
                description="Скасувати" if lang_code == "uk" else "Cancel",
            ),
        ]
        await bot.set_my_commands(
            cmds, scope=BotCommandScopeDefault(), language_code=lang_code
        )


@router.message(or_f(Command("start"), Command("help")))
async def cmd_start_handler(
    message: Message, state: FSMContext, bot: Bot, command: CommandObject = None
):
    lang = await get_lang(message.from_user.id, message)
    await handle_start_command(message, state, bot, command, lang)


@router.message(Command("link"))
async def cmd_link(message: Message):
    lang = await get_lang(message.from_user.id, message)
    link = get_user_link(message.from_user.id)
    await message.answer(
        l10n.format_value("your_link", lang, link=link), parse_mode="HTML"
    )


@router.message(Command("settings"))
async def cmd_settings(message: Message):
    lang = await get_lang(message.from_user.id, message)
    settings = db.get_user_settings(message.from_user.id)
    kb = get_settings_keyboard(lang, settings)
    await message.answer(
        l10n.format_value("settings_title", lang), reply_markup=kb, parse_mode="HTML"
    )


@router.message(Command("set_voice"))
async def cmd_voice_setting(message: Message, command: CommandObject):
    lang = db.get_user_lang(message.from_user.id)
    await handle_voice_setting(message, command.args, lang)


@router.message(or_f(Command("list_voices"), Command("voice_list")))
async def cmd_list_voices(message: Message):
    lang = db.get_user_lang(message.from_user.id)
    await handle_list_voices(message, lang)


@router.message(Command("report"))
async def cmd_report(message: Message):
    lang = db.get_user_lang(message.from_user.id)
    await handle_report(message, lang)


@router.message(Command("admin"))
async def cmd_admin(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    lang = db.get_user_lang(message.from_user.id)
    await handle_admin_stats(message, lang)


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext):
    await state.clear()
    lang = await get_lang(message.from_user.id, message)
    await message.answer(l10n.format_value("writing_stopped", lang) or "Скасовано.")
