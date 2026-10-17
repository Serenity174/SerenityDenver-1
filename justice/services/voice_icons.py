import logging

import discord

from justice.config import PROJECT_ROOT

log = logging.getLogger(__name__)
VOICE_BUTTONS = {
    "tempvoice-lock": ("lock", "Доступ"),
    "tempvoice-hide": ("glaza", "Видимость"),
    "tempvoice-limit": ("limit", "Лимит"),
    "tempvoice-rename": ("redact", "Название"),
    "tempvoice-transfer": ("korona", "Владелец"),
    "tempvoice-allow": ("adduser", "Разрешить"),
    "tempvoice-block": ("zapret", "Запретить"),
}


async def load_voice_icons(bot):
    """Upload once per application, then reuse its existing custom emojis."""
    bot.voice_icons = {}
    if not bot.application_id:
        return
    try:
        emojis = {emoji.name: emoji for emoji in await bot.fetch_application_emojis()}
        for name, _ in VOICE_BUTTONS.values():
            emoji_name = f"justice_{name}"
            emoji = emojis.get(emoji_name)
            if emoji is None:
                emoji = await bot.create_application_emoji(
                    name=emoji_name,
                    image=(PROJECT_ROOT / "assets" / "voice" / f"{name}.png").read_bytes(),
                )
            bot.voice_icons[name] = emoji
    except discord.HTTPException:
        log.exception("Could not register white voice icons; using text button labels")
