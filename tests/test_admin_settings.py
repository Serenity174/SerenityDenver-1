import copy
import unittest
from dataclasses import replace
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from serenity.cogs.admin import EditSetting, Home, Images, Prices, SettingsList
from serenity.config import get_settings
from serenity.services.contract_rules import active_slots, role_priority
from serenity.services.reporting import report_total
from serenity.services.settings import LiveSettings, SettingSpec, enabled, set_live, validate
from serenity.services.settings_defaults import defaults


class AdminSettingsTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.settings = replace(get_settings())
        self.service = LiveSettings(None, self.settings, defaults(self.settings))
        for key, value in self.service.defaults.items():
            self.service.apply(key, copy.deepcopy(value))
        self.bot = SimpleNamespace(live_settings=self.service)
        set_live(self.service)

    async def asyncTearDown(self):
        set_live(None)

    async def test_all_defaults_are_valid_and_no_secrets_are_exposed(self):
        self.assertEqual(set(self.service.defaults), set(self.service.specs))
        self.assertFalse(
            {"token", "database_url", "google_credentials_path", "guild_id"}
            & self.service.specs.keys()
        )
        for key, value in self.service.defaults.items():
            with self.subTest(key=key):
                validate(self.service.specs[key], value)

    async def test_all_menu_pages_fit_discord_limits(self):
        Home(self.bot, 1)
        for group in {spec.group for spec in self.service.specs.values()}:
            count = sum(spec.group == group for spec in self.service.specs.values())
            for page in range((count + 24) // 25):
                view = SettingsList(self.bot, 1, group, page)
                selects = [item for item in view.children if hasattr(item, "options")]
                self.assertLessEqual(len(selects[0].options), 25)
        for key, spec in self.service.specs.items():
            if spec.kind not in ("prices", "urls"):
                EditSetting(self.bot, 1, key)
        Prices(self.bot, 1, 1)
        for page in range((len(self.service.values["news_images"].splitlines()) + 24) // 25):
            Images(self.bot, 1, "news_images", page)

    async def test_new_prices_and_deleted_categories_affect_new_reports(self):
        self.service.apply("prices", {"Железо": "70.125", "Новая категория": "2"})
        self.assertEqual(report_total("Железо", 2), Decimal("140.25"))
        self.assertEqual(report_total("Новая категория", 3), Decimal("6.00"))
        with self.assertRaises(ValueError):
            report_total("Марлин", 1)

    async def test_live_values_change_only_after_successful_commit(self):
        self.service.repo.save = AsyncMock(side_effect=RuntimeError("unavailable"))
        old = self.service.values["contract_slots"]
        with self.assertRaises(RuntimeError):
            await self.service.save("contract_slots", 8, 1, old)
        self.assertEqual(active_slots(), old)
        self.service.repo.save = AsyncMock()
        await self.service.save("contract_slots", 8, 1, old)
        self.assertEqual(active_slots(), 8)

    async def test_conflicting_edit_does_not_change_runtime(self):
        self.service.repo.save = AsyncMock(side_effect=ValueError("conflict"))
        with self.assertRaises(ValueError):
            await self.service.save("attendance_reward", "1", 1, "40000")
        self.assertEqual(self.service.values["attendance_reward"], "40000")

    async def test_channels_apply_to_shared_settings_identity(self):
        reference = self.service.settings
        self.service.repo.save = AsyncMock()
        await self.service.save(
            "welcome_channel_id", 1234, 1, self.service.values["welcome_channel_id"]
        )
        self.assertIs(reference, self.service.settings)
        self.assertEqual(reference.welcome_channel_id, 1234)

    async def test_disabling_features_is_immediate(self):
        self.assertTrue(enabled("reports"))
        self.service.apply("enabled:reports", False)
        self.assertFalse(enabled("reports"))

    async def test_private_menu_rejects_other_users_and_revoked_roles(self):
        view = Home(self.bot, 1)
        interaction = SimpleNamespace(
            guild_id=get_settings().guild_id,
            user=SimpleNamespace(
                id=2,
                guild=SimpleNamespace(id=get_settings().guild_id),
                guild_permissions=SimpleNamespace(administrator=True),
                roles=[],
            ),
            response=SimpleNamespace(is_done=lambda: False, send_message=AsyncMock()),
        )
        self.assertFalse(await view.interaction_check(interaction))
        interaction.user.id = 1
        self.assertTrue(await view.interaction_check(interaction))
        interaction.user.guild_permissions.administrator = False
        self.assertFalse(await view.interaction_check(interaction))

    async def test_role_priority_is_computed_from_current_roles(self):
        original = get_settings()
        old_ranks, old_staff = original.rank_role_ids, original.high_staff_role_id
        try:
            object.__setattr__(original, "rank_role_ids", (100, 200))
            object.__setattr__(original, "high_staff_role_id", 300)
            self.assertEqual(role_priority(), {100: 1, 200: 2, 300: 3})
        finally:
            object.__setattr__(original, "rank_role_ids", old_ranks)
            object.__setattr__(original, "high_staff_role_id", old_staff)

    async def test_invalid_prices_times_and_urls_are_rejected(self):
        for value in ("NaN", "Infinity", "-1", "0.00001", "1000000001"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate(SettingSpec("", "", "money"), value)
        for value in ("24:00", "12:60", "tomorrow"):
            with self.assertRaises(ValueError):
                validate(SettingSpec("", "", "time"), value)
        for value in (
            "file:///secret",
            "http://example.com/a.png",
            "https://user:password@example.com/a.png",
        ):
            with self.assertRaises(ValueError):
                validate(SettingSpec("", "", "url"), value)
        self.assertEqual(validate(SettingSpec("", "", "category"), 0), 0)

    async def test_expired_report_form_is_blocked_after_disabling_reports(self):
        from serenity.cogs.report_db import DBReportModal

        interaction = SimpleNamespace(
            guild_id=get_settings().guild_id,
            data={},
            response=SimpleNamespace(
                is_done=lambda: False, send_message=AsyncMock(), defer=AsyncMock()
            ),
        )
        self.service.apply("enabled:reports", False)
        await DBReportModal("Железо", None).on_submit(interaction)
        interaction.response.defer.assert_not_awaited()
        interaction.response.send_message.assert_awaited_once()

    async def test_vacation_return_remains_available_when_new_vacations_are_disabled(self):
        from serenity.services.settings import feature_check

        self.service.apply("enabled:Otpysk", False)
        interaction = SimpleNamespace(data={"custom_id": "vacation_return"})
        self.assertTrue(await feature_check(interaction, "serenity.cogs.Otpysk"))

    async def test_report_delivery_recovers_message_after_interrupted_commit(self):
        from datetime import datetime, timezone

        import discord

        from serenity.cogs.jobs import Jobs

        embed = discord.Embed(title="Отчёт")
        embed.set_footer(text="ID записи: 12")
        delivered = SimpleNamespace(author=SimpleNamespace(id=55), embeds=[embed])

        async def history(**kwargs):
            yield delivered

        channel = SimpleNamespace(history=history, send=AsyncMock())
        pool = SimpleNamespace(
            fetchrow=AsyncMock(return_value={"created_at": datetime.now(timezone.utc)})
        )
        bot = SimpleNamespace(
            database=SimpleNamespace(pool=pool),
            get_channel=lambda channel_id: channel,
            user=SimpleNamespace(id=55),
        )
        await Jobs(bot).dispatch(
            {
                "kind": "report_publication",
                "payload": {"channel_id": 88, "report_id": 12, "embed": embed.to_dict()},
            }
        )
        channel.send.assert_not_awaited()
        pool.fetchrow.return_value = None
        await Jobs(bot).dispatch(
            {
                "kind": "report_publication",
                "payload": {"channel_id": 88, "report_id": 12, "embed": embed.to_dict()},
            }
        )
        channel.send.assert_not_awaited()

    async def test_panel_reuses_existing_message_without_deleting_history(self):
        from serenity.services.panels import publish_panel

        message = SimpleNamespace(id=77, edit=AsyncMock())
        channel = SimpleNamespace(fetch_message=AsyncMock(return_value=message), send=AsyncMock())
        bot = SimpleNamespace(
            settings=self.settings,
            database=SimpleNamespace(pool=None),
            get_channel=lambda channel_id: channel,
        )
        state = SimpleNamespace(
            get=AsyncMock(
                return_value={
                    "channel_id": self.settings.report_interface_channel_id,
                    "message_id": 77,
                }
            ),
            put=AsyncMock(),
        )
        with patch("serenity.services.panels.StateRepository", return_value=state):
            self.assertIs(await publish_panel(bot, "reports"), message)
        message.edit.assert_awaited_once()
        channel.send.assert_not_awaited()
        state.put.assert_awaited_once()
