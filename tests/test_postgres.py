import asyncio
import os
import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
from urllib.parse import urlsplit

from serenity.config import get_settings
from serenity.database import MIGRATIONS, Database, migrate, set_database
from serenity.repositories.contracts import ContractDB
from serenity.repositories.jobs import JobRepository
from serenity.repositories.payouts import PayoutRepository
from serenity.repositories.reports import ReportRepository
from serenity.repositories.requests import RequestRepository
from serenity.repositories.state import StateRepository

TEST_URL = os.environ.get("TEST_DATABASE_URL")


@unittest.skipUnless(
    TEST_URL, "Set TEST_DATABASE_URL to a dedicated serenity_test PostgreSQL database"
)
class PostgreSQLTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        if urlsplit(TEST_URL).path != "/serenity_test":
            self.fail("TEST_DATABASE_URL must target the dedicated serenity_test database")
        self.db = Database(TEST_URL)
        await self.db.open()
        # Never reset data in a working deployment, even if a URL is pasted by mistake.
        if await self.db.pool.fetchval("SELECT current_database()") != "serenity_test":
            await self.db.close()
            self.fail("Integration tests require a database named serenity_test")
        await self.db.pool.execute("""TRUNCATE public.bot_state, public.birthdays, public.requests,
            public.jobs, public.contract_signups, public.attendance_events, public.contracts,
            public.contract_users, public.reports, public.give, public.payout_runs,
            public.admin_settings, public.settings_history,
            public.contract_meta RESTART IDENTITY CASCADE""")
        set_database(self.db)

    async def asyncTearDown(self):
        await self.db.close()
        set_database(None)

    async def test_migrations_preserve_existing_rows_and_reject_modified_history(self):
        repo = StateRepository(self.db.pool)
        await repo.put(1, "test", "key", {"value": 1})
        await migrate(self.db.pool)
        self.assertEqual(await repo.get(1, "test", "key"), {"value": 1})
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            for file in MIGRATIONS.glob("*.sql"):
                (path / file.name).write_bytes(file.read_bytes() + b"\n-- modified")
            with self.assertRaisesRegex(RuntimeError, "Applied migration changed"):
                await migrate(self.db.pool, path)
        self.assertEqual(await repo.get(1, "test", "key"), {"value": 1})

    async def test_state_survives_new_connection(self):
        await StateRepository(self.db.pool).put(
            1, "voice", 44, {"owner_id": 55, "allowed_users": [66]}
        )
        other = Database(TEST_URL)
        try:
            await other.open()
            self.assertEqual(
                (await StateRepository(other.pool).get(1, "voice", 44))["owner_id"], 55
            )
        finally:
            await other.close()

    async def test_admin_settings_persist_history_and_reject_stale_edits(self):
        from serenity.repositories.settings import SettingsRepository

        repo = SettingsRepository(self.db.pool)
        initial = {"contract_slots": 5, "prices": {"Железо": "61"}}
        self.assertEqual(await repo.seed(1, initial), initial)
        await repo.save(1, "contract_slots", 8, 99, 5)
        self.assertEqual((await repo.seed(1, initial))["contract_slots"], 8)
        with self.assertRaises(ValueError):
            await repo.save(1, "contract_slots", 10, 100, 5)
        history = await repo.history(1)
        self.assertEqual(len(history), 1)
        self.assertEqual(
            (history[0]["old_value"], history[0]["new_value"], history[0]["actor_id"]), (5, 8, 99)
        )

    async def test_report_and_publication_job_are_saved_once(self):
        repo = ReportRepository(self.db.pool)

        async def create():
            return await repo.create(
                interaction_id=777,
                nickname="Test",
                static_id=5,
                category="Железо",
                quantity=1,
                total=Decimal("61"),
                proof="https://example.com/proof",
                user_id=5,
                username="test",
                publication={"channel_id": 100, "embed": {"title": "Отчёт"}},
            )

        values = await asyncio.gather(*(create() for _ in range(5)))
        record_id = next(value for value in values if value is not None)
        jobs = await self.db.pool.fetch(
            "SELECT payload FROM public.jobs WHERE kind='report_publication'"
        )
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]["payload"]["report_id"], record_id)
        self.assertEqual(jobs[0]["payload"]["embed"]["footer"]["text"], f"ID записи: {record_id}")

    async def test_report_is_rolled_back_if_publication_cannot_be_saved(self):
        repo = ReportRepository(self.db.pool)
        with self.assertRaises(TypeError):
            await repo.create(
                interaction_id=778,
                nickname="Test",
                static_id=5,
                category="Железо",
                quantity=1,
                total=Decimal("61"),
                proof="https://example.com/proof",
                user_id=5,
                username="test",
                publication={"embed": None},
            )
        self.assertEqual(
            await self.db.pool.fetchval(
                "SELECT count(*) FROM public.reports WHERE interaction_id=778"
            ),
            0,
        )

    async def test_only_one_bot_holds_guild_lease(self):
        await self.db.acquire_bot_lease(987654)
        other = Database(TEST_URL)
        try:
            await other.open()
            with self.assertRaisesRegex(RuntimeError, "Another Serenity"):
                await other.acquire_bot_lease(987654)
            await self.db.check_lease()
        finally:
            await other.close()

    async def test_concurrent_reports_store_once(self):
        repo = ReportRepository(self.db.pool)

        async def create():
            return await repo.create(
                interaction_id=101,
                nickname="Test",
                static_id=5,
                category="Марлин",
                quantity=10,
                total=Decimal("8.58"),
                proof="https://example.com/proof",
                user_id=5,
                username="test",
            )

        values = await asyncio.gather(*(create() for _ in range(8)))
        self.assertEqual(sum(value is not None for value in values), 1)
        self.assertEqual(
            await self.db.pool.fetchval("SELECT sum(total) FROM public.reports"), Decimal("8.58")
        )

    async def test_attendance_marking_is_atomic_and_limited(self):
        repo = ContractDB(self.db.pool)
        for user_id in range(1, 9):
            await repo.upsert_user(user_id, 1)
        contract = await repo.create_contract(100, 200, 1)
        for user_id in range(1, 9):
            await repo.add_signup(contract, user_id)
        values = await asyncio.gather(*(repo.mark_attendance(contract, 99) for _ in range(6)))
        self.assertEqual(sum(values), 5)
        self.assertEqual(
            await self.db.pool.fetchval("SELECT count(*) FROM public.attendance_events"), 5
        )
        self.assertEqual(
            await self.db.pool.fetchval("SELECT sum(total_attendance) FROM public.contract_users"),
            5,
        )

    async def test_pending_request_deduplication_and_transaction_rollback(self):
        repo = RequestRepository(self.db.pool)
        values = await asyncio.gather(
            *(repo.create(1, 2, "promotion", {"target_role_id": 3}, 100 + i) for i in range(6))
        )
        self.assertEqual(sum(created for _, created in values), 1)
        request_id = values[0][0]["id"]
        with self.assertRaises(RuntimeError):
            async with repo.locked(request_id) as (conn, row):
                await repo.finish(conn, row["id"], "accepted", 7)
                raise RuntimeError("Discord failed")
        self.assertEqual((await repo.get(request_id))["status"], "pending")
        async with repo.locked(request_id) as (conn, row):
            await repo.finish(conn, row["id"], "accepted", 7)
        self.assertEqual((await repo.get(request_id))["handled_by"], 7)

    async def test_jobs_dedupe_claim_and_recover_expired_lease(self):
        repo = JobRepository(self.db.pool)
        now = datetime.now(timezone.utc)
        for _ in range(3):
            await repo.schedule("dm", "same", {"user_id": 1}, now, now + timedelta(hours=1))
        rows = await asyncio.gather(*(repo.claim() for _ in range(5)))
        claimed = [row for row in rows if row]
        self.assertEqual(len(claimed), 1)
        job_id = claimed[0]["id"]
        await self.db.pool.execute(
            "UPDATE public.jobs SET lease_until=now()-interval '1 second' WHERE id=$1", job_id
        )
        self.assertEqual((await repo.claim())["id"], job_id)
        await repo.complete(job_id)
        self.assertIsNone(await repo.claim())

    async def test_giveaway_concurrent_entries_and_stable_winners(self):
        from serenity.repositories.giveaways import (
            pg_choose_winners,
            pg_create_give,
            pg_get_user_ids,
            pg_toggle_entry,
        )

        now = datetime.now(timezone.utc)
        giveaway = await pg_create_give(1, 2, "Prize", 2, now + timedelta(hours=1), 3)
        await asyncio.gather(*(pg_toggle_entry(giveaway, user_id) for user_id in range(1, 21)))
        self.assertEqual(len(await pg_get_user_ids(giveaway)), 20)
        winners = await asyncio.gather(*(pg_choose_winners(giveaway) for _ in range(5)))
        self.assertTrue(all(value == winners[0] for value in winners))
        await self.db.pool.execute("UPDATE public.give SET finished=TRUE WHERE id=$1", giveaway)
        with self.assertRaises(ValueError):
            await pg_toggle_entry(giveaway, 40)

    async def test_payout_snapshot_is_immutable(self):
        repo = PayoutRepository(self.db.pool)
        week = datetime.now(timezone.utc).date()
        await repo.snapshot(1, week, [{"user_id": 2, "amount": Decimal("40000.01")}])
        run = await repo.snapshot(1, week, [{"user_id": 2, "amount": Decimal("999999")}])
        self.assertEqual(run["payload"][0]["amount"], "40000.01")
        await repo.message_sent(1, week, "embed", 55)
        await repo.finish(1, week)
        run = await repo.snapshot(1, week, [])
        self.assertEqual(run["embed_message_id"], 55)
        self.assertIsNotNone(run["completed_at"])

    async def test_all_extensions_start_and_share_one_pool(self):
        from serenity.bot import EXTENSIONS, SerenityBot

        bot = SerenityBot(replace(get_settings(), database_url=TEST_URL, token="test-token"))
        await bot._async_setup_hook()
        try:
            await bot.setup_hook()
            self.assertEqual(len(bot.extensions), len(EXTENSIONS))
            self.assertIs(bot.get_cog("ContractsCog").db.pool, bot.database.pool)
            self.assertIs(bot.get_cog("CarsCog").repo.pool, bot.database.pool)
            self.assertIs(bot.get_cog("Payouts").pool, bot.database.pool)
            self.assertIs(bot.get_cog("ReportDB").db_pool, bot.database.pool)
        finally:
            await bot.close()
            set_database(self.db)

    async def test_request_publication_adopts_message_after_interrupted_commit(self):
        import discord

        from serenity.services.workflows import publish_request

        repo = RequestRepository(self.db.pool)
        row, _ = await repo.create(1, 2, "bonus", {})
        embed = discord.Embed(title="Saved request")
        embed.set_footer(text=f"Заявка #{row['id']}")
        message = SimpleNamespace(id=77, author=SimpleNamespace(id=88), embeds=[embed])

        async def history(**kwargs):
            yield message

        channel = SimpleNamespace(id=99, history=history, send=AsyncMock())
        bot = SimpleNamespace(user=SimpleNamespace(id=88), add_view=Mock())
        await asyncio.gather(*(publish_request(bot, repo, row["id"], channel) for _ in range(3)))
        channel.send.assert_not_awaited()
        self.assertEqual((await repo.get(row["id"]))["message_id"], 77)

    async def test_published_requests_show_history_for_same_user_and_kind(self):
        import discord

        from serenity.services.workflows import publish_request

        repo = RequestRepository(self.db.pool)

        async def history(**kwargs):
            for message in []:
                yield message

        channel = SimpleNamespace(
            id=99, history=history, send=AsyncMock(return_value=SimpleNamespace(id=77))
        )
        bot = SimpleNamespace(user=SimpleNamespace(id=88), add_view=Mock())
        first, _ = await repo.create(
            1, 2, "application", {"_embed": discord.Embed(title="Test").to_dict()}
        )
        await publish_request(bot, repo, first["id"], channel)
        self.assertEqual(
            channel.send.call_args.kwargs["embed"].fields[-1].value, "Заявка оформлена впервые."
        )
        async with repo.locked(first["id"]) as (conn, row):
            await repo.finish(conn, row["id"], "rejected", 10)
        second, _ = await repo.create(1, 2, "application", {})
        channel.send.return_value = SimpleNamespace(id=78)
        await publish_request(bot, repo, second["id"], channel)
        field = channel.send.call_args.kwargs["embed"].fields[-1]
        self.assertEqual(field.name, "Прошлые заявки:")
        self.assertIn("https://discord.com/channels/1/99/77", field.value)
        self.assertNotIn("/78", field.value)
        async with self.db.pool.acquire() as conn:
            for overrides in ({"user_id": 3}, {"guild_id": 3}, {"kind": "bonus"}):
                self.assertEqual(await repo.previous(conn, {**dict(second), **overrides}), [])

    async def test_promotion_retry_after_discord_failure_keeps_original_target(self):
        from serenity.services.workflows import resolve_request

        settings = get_settings()
        roles = [SimpleNamespace(id=uid) for uid in settings.rank_role_ids]
        member = SimpleNamespace(roles=[roles[0]])

        async def add_roles(role, **kwargs):
            if role not in member.roles:
                member.roles.append(role)

        member.add_roles = AsyncMock(side_effect=add_roles)
        member.remove_roles = AsyncMock(side_effect=RuntimeError("Discord disconnected"))
        guild = SimpleNamespace(
            get_member=lambda uid: member,
            get_role=lambda uid: next(role for role in roles if role.id == uid),
        )
        interaction = SimpleNamespace(
            guild_id=settings.guild_id, guild=guild, user=SimpleNamespace(id=99)
        )
        repo = RequestRepository(self.db.pool)
        row, _ = await repo.create(
            settings.guild_id, 2, "promotion", {"target_role_id": roles[1].id}
        )
        with patch("serenity.services.workflows.can_review", return_value=True):
            with self.assertRaises(RuntimeError):
                await resolve_request(interaction, row["id"], True)
            self.assertEqual((await repo.get(row["id"]))["status"], "pending")
            member.remove_roles.side_effect = None
            result, changed = await resolve_request(interaction, row["id"], True)
            self.assertTrue(changed)
            self.assertEqual(result["status"], "accepted")
            self.assertTrue(
                all(call.args[0].id == roles[1].id for call in member.add_roles.await_args_list)
            )
            _, changed = await resolve_request(interaction, row["id"], True)
            self.assertFalse(changed)
            self.assertEqual(member.add_roles.await_count, 2)
        with patch("serenity.services.workflows.can_review", return_value=False):
            with self.assertRaises(PermissionError):
                await resolve_request(interaction, row["id"], False)

    async def test_signup_concurrent_views_respect_capacity(self):
        from serenity.cogs.bronya import SignUpView

        users = {uid: SimpleNamespace(id=uid, mention=f"<@{uid}>") for uid in range(1, 8)}
        guild = SimpleNamespace(id=1, get_member=users.get)
        message = SimpleNamespace(id=123, guild=guild, channel=SimpleNamespace(id=99))
        first = SignUpView(users[1], 3, "Signup", message=message)
        await first.persist()

        async def join(uid):
            # Each restored view starts with stale state; the lock must reload it.
            view = SignUpView(users[1], 3, "Signup", message=message)
            interaction = SimpleNamespace(
                guild=guild,
                user=users[uid],
                response=SimpleNamespace(edit_message=AsyncMock(), send_message=AsyncMock()),
            )
            await view.join.callback(interaction)

        await asyncio.gather(*(join(uid) for uid in users))
        saved = await StateRepository().get(1, "bronya", 123)
        self.assertEqual(len(saved["participants"]), 3)
        self.assertEqual(len(set(saved["participants"])), 3)

    async def test_voice_state_restores_owner_and_permissions(self):
        from serenity.cogs.temp_voice import TempVoiceChannelInfo
        from serenity.services.voice_state import load_channels, save_channel

        channel = SimpleNamespace(id=123, guild=SimpleNamespace(id=1))
        info = TempVoiceChannelInfo(owner_id=55, allowed_users={66}, blocked_users={77})
        await save_channel(channel, info)
        active = {}
        await load_channels(active, TempVoiceChannelInfo)
        self.assertEqual(active[123].owner_id, 55)
        self.assertEqual(active[123].allowed_users, {66})
        self.assertEqual(active[123].blocked_users, {77})
