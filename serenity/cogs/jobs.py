import logging
from datetime import datetime, timezone

import discord
from discord.ext import commands, tasks

from serenity.repositories.jobs import JobRepository

log = logging.getLogger(__name__)


class Jobs(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.repo = JobRepository(bot.database.pool)

    async def cog_load(self):
        self.worker.start()

    def cog_unload(self):
        self.worker.cancel()

    @tasks.loop(seconds=10)
    async def worker(self):
        for _ in range(20):
            try:
                row = await self.repo.claim()
                if row is None:
                    return
                await self.dispatch(row)
                await self.repo.complete(row["id"])
            except Exception as exc:
                log.exception("Job processing failed")
                if "row" in locals() and row:
                    await self.repo.retry(row["id"], type(exc).__name__)
                return

    @worker.before_loop
    async def before_worker(self):
        await self.bot.wait_until_ready()

    async def dispatch(self, row):
        payload = row["payload"]
        if row["kind"] == "report_publication":
            report = await self.bot.database.pool.fetchrow(
                "SELECT created_at FROM public.reports WHERE id=$1", payload["report_id"]
            )
            if report is None:
                return
            channel = self.bot.get_channel(payload["channel_id"]) or await self.bot.fetch_channel(
                payload["channel_id"]
            )
            marker = f"ID записи: {payload['report_id']}"
            async for message in channel.history(limit=None, after=report["created_at"]):
                if (
                    message.author.id == self.bot.user.id
                    and message.embeds
                    and message.embeds[0].footer.text == marker
                ):
                    return
            await channel.send(embed=discord.Embed.from_dict(payload["embed"]))
        elif row["kind"] == "contract_reminder":
            from serenity.services.contract_rules import active_slots

            cog = self.bot.get_cog("ContractsCog")
            contract = await self.bot.database.pool.fetchrow(
                "SELECT * FROM public.contracts WHERE id=$1", payload["contract_id"]
            )
            if contract is None:
                return
            signups = await cog.db.fetch_signups(contract["id"], False)
            ids = list(dict.fromkeys([contract["host_id"]] + [r["user_id"] for r in signups]))[
                : active_slots()
            ]
            for user_id in ids:
                await self.repo.schedule(
                    "dm",
                    f"contract:{contract['id']}:{user_id}",
                    {"user_id": user_id, "content": payload["content"]},
                    datetime.now(timezone.utc),
                    row["expires_at"],
                )
        elif row["kind"] == "dm":
            try:
                user = self.bot.get_user(payload["user_id"]) or await self.bot.fetch_user(
                    payload["user_id"]
                )
                await user.send(payload["content"])
            except (discord.Forbidden, discord.NotFound):
                log.info("Reminder recipient unavailable user=%s", payload["user_id"])
        elif row["kind"] == "channel_message":
            channel = self.bot.get_channel(payload["channel_id"]) or await self.bot.fetch_channel(
                payload["channel_id"]
            )
            await channel.send(payload["content"])
        else:
            raise ValueError("Unknown job kind")


async def setup(bot):
    await bot.add_cog(Jobs(bot))
