import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import discord
from discord import app_commands

from serenity.bot import SerenityBot
from serenity.config import get_settings


class CommandSyncTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.bot = SerenityBot(get_settings())
        self.bot.tree.sync = AsyncMock(return_value=[SimpleNamespace(name="настройки")])

        async def callback(interaction):
            pass

        self.bot.tree.add_command(
            app_commands.Command(name="настройки", description="Настройки", callback=callback),
            guild=discord.Object(id=self.bot.settings.guild_id),
        )

    async def asyncTearDown(self):
        await self.bot.close()

    async def test_startup_waits_for_ready_before_syncing(self):
        self.bot.wait_until_ready = AsyncMock()
        self.bot.get_guild = Mock(return_value=object())
        await self.bot._sync_commands_on_ready()
        self.bot.wait_until_ready.assert_awaited_once()
        self.bot.tree.sync.assert_awaited_once()
        self.assertEqual(
            self.bot.tree.sync.call_args.kwargs["guild"].id, self.bot.settings.guild_id
        )

    async def test_incomplete_tree_is_not_published(self):
        self.bot.tree.remove_command(
            "настройки", guild=discord.Object(id=self.bot.settings.guild_id)
        )
        with self.assertRaises(RuntimeError):
            await self.bot.sync_guild_commands()
        self.bot.tree.sync.assert_not_awaited()

    async def test_missing_guild_does_not_publish_commands(self):
        self.bot.wait_until_ready = AsyncMock()
        self.bot.get_guild = Mock(return_value=None)
        with self.assertLogs("serenity.bot", level="ERROR"):
            await self.bot._sync_commands_on_ready()
        self.bot.tree.sync.assert_not_awaited()

    async def test_transient_discord_failure_retries(self):
        self.bot.wait_until_ready = AsyncMock()
        self.bot.get_guild = Mock(return_value=object())
        failure = discord.HTTPException(SimpleNamespace(status=503, reason="Unavailable"), "Retry")
        self.bot.tree.sync.side_effect = [failure, []]
        with (
            patch("serenity.bot.asyncio.sleep", new_callable=AsyncMock),
            self.assertLogs("serenity.bot", level="ERROR"),
        ):
            await self.bot._sync_commands_on_ready()
        self.assertEqual(self.bot.tree.sync.await_count, 2)

    async def test_server_admin_can_sync_without_being_application_owner(self):
        guild = SimpleNamespace(id=self.bot.settings.guild_id)
        author = SimpleNamespace(
            guild=guild, guild_permissions=SimpleNamespace(administrator=True), roles=[]
        )
        ctx = SimpleNamespace(guild=guild, author=author, send=AsyncMock())
        self.bot.is_owner = AsyncMock(return_value=False)
        await self.bot.sync_command.callback(self.bot, ctx)
        self.bot.tree.sync.assert_awaited_once()
        self.bot.is_owner.assert_not_awaited()

    async def test_regular_member_cannot_sync(self):
        guild = SimpleNamespace(id=self.bot.settings.guild_id)
        ctx = SimpleNamespace(
            guild=guild,
            author=SimpleNamespace(
                guild=guild, guild_permissions=SimpleNamespace(administrator=False), roles=[]
            ),
            send=AsyncMock(),
        )
        self.bot.is_owner = AsyncMock(return_value=False)
        await self.bot.sync_command.callback(self.bot, ctx)
        self.bot.tree.sync.assert_not_awaited()

    async def test_mentions_work_alongside_configured_prefix(self):
        self.bot._connection.user = SimpleNamespace(id=123)
        prefixes = await self.bot.get_prefix(SimpleNamespace(content="<@123> sync"))
        self.assertIn("<@123> ", prefixes)
        self.assertIn(self.bot.settings.bot_command_prefix, prefixes)
