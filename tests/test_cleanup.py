import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import discord
from discord import app_commands

from justice.cogs.cleanup import Cleanup


class CleanupTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.cog = Cleanup(SimpleNamespace())
        self.channel = Mock(spec=discord.TextChannel)
        self.channel.id = 10
        self.channel.fetch_message = AsyncMock()
        self.channel.purge = AsyncMock(return_value=[Mock(), Mock()])
        self.interaction = SimpleNamespace(
            id=1000,
            channel=self.channel,
            user=SimpleNamespace(id=20),
            response=SimpleNamespace(defer=AsyncMock(), is_done=lambda: True),
            followup=SimpleNamespace(send=AsyncMock()),
        )

    async def test_includes_boundary_and_excludes_messages_after_invocation(self):
        await self.cog.clear.callback(self.cog, self.interaction, "500")
        self.channel.fetch_message.assert_awaited_once_with(500)
        options = self.channel.purge.call_args.kwargs
        self.assertEqual(options["after"].id, 499)
        self.assertEqual(options["before"].id, 1000)
        self.assertIsNone(options["limit"])
        self.interaction.followup.send.assert_awaited_once_with(
            "Удалено сообщений: 2.", ephemeral=True
        )

    async def test_invalid_or_future_id_never_deletes(self):
        for value in ("invalid", "0", "-1", "1000", "2000", "https://discord.com/500"):
            await self.cog.clear.callback(self.cog, self.interaction, value)
        self.channel.fetch_message.assert_not_awaited()
        self.channel.purge.assert_not_awaited()

    async def test_message_from_another_channel_never_deletes(self):
        self.channel.fetch_message.side_effect = discord.NotFound(
            SimpleNamespace(status=404, reason="Not Found"), "Unknown Message"
        )
        await self.cog.clear.callback(self.cog, self.interaction, "500")
        self.channel.purge.assert_not_awaited()

    async def test_missing_user_or_bot_permissions_are_rejected(self):
        for user_allowed, bot_allowed, error in (
            (False, True, app_commands.MissingPermissions),
            (True, False, app_commands.BotMissingPermissions),
        ):
            self.interaction.permissions = discord.Permissions(manage_messages=user_allowed)
            self.interaction.app_permissions = discord.Permissions(
                manage_messages=bot_allowed, read_message_history=True, view_channel=True
            )
            with self.assertRaises(error):
                for check in self.cog.clear.checks:
                    await discord.utils.maybe_coroutine(check, self.interaction)
        self.channel.purge.assert_not_awaited()
