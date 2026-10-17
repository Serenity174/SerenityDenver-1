import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

import discord

from justice.cogs.temp_voice import TempVoicePanelView
from justice.services.voice_icons import VOICE_BUTTONS, load_voice_icons
from justice.ui.emojis import CLOUDS, JUSTICE, LOADING, normalize_emojis


class VoiceIconTests(unittest.IsolatedAsyncioTestCase):
    async def test_creates_white_application_emojis_once_and_uses_them_on_buttons(self):
        created = []

        async def create(*, name, image):
            self.assertTrue(image.startswith(b"\x89PNG"))
            emoji = discord.PartialEmoji(name=name, id=100 + len(created))
            created.append(emoji)
            return emoji

        bot = SimpleNamespace(
            application_id=1,
            fetch_application_emojis=AsyncMock(side_effect=lambda: list(created)),
            create_application_emoji=AsyncMock(side_effect=create),
        )
        await load_voice_icons(bot)
        self.assertEqual(bot.create_application_emoji.await_count, 7)
        await load_voice_icons(bot)
        self.assertEqual(bot.create_application_emoji.await_count, 7)
        view = TempVoicePanelView(bot)
        for button in view.children:
            name, _ = VOICE_BUTTONS[button.custom_id]
            self.assertEqual(button.emoji.name, f"justice_{name}")
            self.assertIsNotNone(button.emoji.id)
            self.assertEqual(button.style, discord.ButtonStyle.secondary)

    async def test_old_custom_emojis_are_normalized_without_changing_other_emojis(self):
        text = (
            "<:justice:1391919340022005900> <:Serenity:1> "
            "<a:loading:1452422282797387806> <a:cloud:1453169995172282418> ✅"
        )
        self.assertEqual(normalize_emojis(text), f"{JUSTICE} {JUSTICE} {LOADING} {CLOUDS} ✅")
