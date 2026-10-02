import asyncio
import logging

import discord
from discord import app_commands
from discord.ext import commands

from serenity.database import Database, set_database
from serenity.ui.base import interaction_error, reply

log = logging.getLogger(__name__)
EXTENSIONS = (
    "contracts",
    "report_db",
    "payouts",
    "attendance_stats",
    "giveaways",
    "cars",
    "applications",
    "promotion",
    "bonus",
    "birthday",
    "Otpysk",
    "bronya",
    "news",
    "welcome",
    "temp_voice",
    "role_parser",
    "embed_modal",
    "jobs",
)


class CommandTree(app_commands.CommandTree):
    async def interaction_check(self, interaction):
        if interaction.guild_id != self.client.settings.guild_id:
            await reply(interaction, "Команды доступны только на сервере семьи.")
            return False
        return True

    async def on_error(self, interaction, error):
        if isinstance(error, app_commands.CheckFailure):
            await reply(interaction, "У вас нет прав для этого действия.")
            return
        await interaction_error(interaction, error)


class SerenityBot(commands.Bot):
    def __init__(self, settings):
        self.settings = settings
        intents = discord.Intents.default()
        intents.members = intents.message_content = intents.voice_states = intents.invites = True
        super().__init__(
            command_prefix=settings.bot_command_prefix,
            intents=intents,
            tree_cls=CommandTree,
            allowed_mentions=discord.AllowedMentions(everyone=False),
        )
        self.database = Database(
            settings.database_url, min_size=settings.db_pool_min, max_size=settings.db_pool_max
        )
        self.background_tasks = set()
        self._closing = False

    def spawn(self, coroutine, *, name):
        task = asyncio.create_task(coroutine, name=name)
        self.background_tasks.add(task)

        def done(completed):
            self.background_tasks.discard(completed)
            if not completed.cancelled() and completed.exception():
                error = completed.exception()
                log.error(
                    "Background task failed: %s",
                    name,
                    exc_info=(type(error), error, error.__traceback__),
                )

        task.add_done_callback(done)
        return task

    async def setup_hook(self):
        await self.database.open()
        await self.database.acquire_bot_lease(self.settings.guild_id)
        set_database(self.database)
        for extension in EXTENSIONS:
            await self.load_extension(f"serenity.cogs.{extension}")
            log.info("Loaded extension %s", extension)
        self.spawn(self._watch_lease(), name="database-lease")

    async def _watch_lease(self):
        while not self.is_closed():
            await asyncio.sleep(15)
            try:
                await self.database.check_lease()
            except Exception:
                log.exception("Lost exclusive bot lease; stopping")
                await self.close()
                return

    async def on_ready(self):
        log.info("Connected as %s; guild=%s", self.user.id, self.settings.guild_id)
        await self.change_presence(
            activity=discord.Activity(
                type=discord.ActivityType.watching, name=self.settings.bot_activity_name
            )
        )

    async def on_error(self, event_method, *args, **kwargs):
        log.exception("Discord event failed: %s", event_method)

    async def on_command_error(self, ctx, error):
        if isinstance(error, commands.CommandNotFound):
            return
        if isinstance(error, commands.CheckFailure):
            await ctx.send("Нет прав для этой команды.")
            return
        log.error(
            "Command failed: %s", ctx.command, exc_info=(type(error), error, error.__traceback__)
        )
        await ctx.send("Не удалось выполнить команду. Ошибка записана в журнал.")

    async def close(self):
        if self._closing:
            return
        self._closing = True
        current = asyncio.current_task()
        pending = [task for task in self.background_tasks if task is not current]
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        try:
            for extension in reversed(tuple(self.extensions)):
                await self.unload_extension(extension)
            await super().close()
        finally:
            await self.database.close()
            set_database(None)
