from aiogram import Router, Bot, types
from aiogram.types import ReactionTypeEmoji, ReactionTypeCustomEmoji
from l10n import l10n
from database import db
from utils import get_lang

router = Router()


@router.message_reaction()
async def on_reaction(reaction: types.MessageReactionUpdated, bot: Bot):
    link = db.get_link_by_receiver(reaction.message_id, reaction.chat.id)
    if not link:
        return

    original_sender_id, original_msg_id, original_chat_id, _ = link

    if reaction.new_reaction:
        emoji = ""
        for r in reaction.new_reaction:
            if r.type == "emoji":
                emoji += r.emoji
            elif r.type == "custom_emoji":
                emoji += f'<tg-emoji emoji-id="{r.custom_emoji_id}">✨</tg-emoji>'

        if emoji:  # Corrected indentation for this block
            lang = await get_lang(original_sender_id)
            try:
                await bot.send_message(
                    original_sender_id,
                    l10n.format_value("reaction_received", lang, emoji=emoji),
                    reply_to_message_id=original_msg_id,
                    parse_mode="HTML",
                )
                # Sync reaction back to sender's message
                sync_reactions = []
                for r in reaction.new_reaction:
                    if r.type == "emoji":
                        sync_reactions.append(ReactionTypeEmoji(emoji=r.emoji))
                    elif r.type == "custom_emoji":
                        sync_reactions.append(
                            ReactionTypeCustomEmoji(custom_emoji_id=r.custom_emoji_id)
                        )

                try:
                    await bot.set_message_reaction(
                        chat_id=original_chat_id,
                        message_id=original_msg_id,
                        reaction=sync_reactions,
                    )
                except Exception:
                    # Fallback to standard star if custom fails
                    try:
                        await bot.set_message_reaction(
                            chat_id=original_chat_id,
                            message_id=original_msg_id,
                            reaction=[ReactionTypeEmoji(emoji="✨")],
                        )
                    except Exception:
                        pass
            except Exception:
                pass
