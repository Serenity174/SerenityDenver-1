import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import discord

from justice.config import get_settings
from justice.services.panels import PANEL_LABELS, publish_panel, refresh_saved_panels
from justice.services.settings import set_live
from justice.services.settings_defaults import defaults


class PanelRefreshTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.settings = get_settings()
        set_live(SimpleNamespace(values=defaults(self.settings)))
        self.addCleanup(set_live, None)

    async def test_entire_panel_moves_below_submission_for_every_panel(self):
        for key in PANEL_LABELS:
            with self.subTest(panel=key):
                old = SimpleNamespace(id=10, delete=AsyncMock(), edit=AsyncMock())
                submission = SimpleNamespace(id=20)
                new = SimpleNamespace(id=30)

                async def history(**kwargs):
                    yield submission

                channel = SimpleNamespace(
                    id=50,
                    fetch_message=AsyncMock(return_value=old),
                    history=history,
                    send=AsyncMock(return_value=new),
                )
                # Each configured channel resolves to the same fake channel for this test.
                channel_ids = {
                    "reports": self.settings.report_interface_channel_id,
                    "application": self.settings.submit_channel_id,
                    "promotion": self.settings.promotion_channel_id,
                    "vacation": self.settings.vacation_channel_id,
                    "birthday": self.settings.birthday_channel_id,
                    "bonus": self.settings.bonus_channel_id,
                }
                channel.id = channel_ids[key]
                state = SimpleNamespace(
                    get=AsyncMock(return_value={"channel_id": channel.id, "message_id": 10}),
                    put=AsyncMock(),
                )
                bot = SimpleNamespace(
                    settings=self.settings,
                    database=SimpleNamespace(pool=None),
                    get_channel=lambda _: channel,
                )
                with patch("justice.services.panels.StateRepository", return_value=state):
                    result = await publish_panel(bot, key, move_to_bottom=True)
                self.assertIs(result, new)
                sent = channel.send.call_args.kwargs
                self.assertIsInstance(sent["embed"], discord.Embed)
                self.assertTrue(sent["view"].children)
                self.assertEqual(sent["embed"].color.value, 0xFFFAFA)
                self.assertIsNotNone(sent["embed"].title)
                self.assertTrue(sent["embed"].description)
                old.delete.assert_awaited_once()
                old.edit.assert_not_awaited()
                self.assertEqual(state.put.call_args.args[-1]["message_id"], 30)

    async def test_failed_new_panel_send_preserves_previous_panel(self):
        old = SimpleNamespace(id=10, delete=AsyncMock())

        async def history(**kwargs):
            yield SimpleNamespace(id=20)

        channel = SimpleNamespace(
            id=self.settings.birthday_channel_id,
            history=history,
            fetch_message=AsyncMock(return_value=old),
            send=AsyncMock(side_effect=RuntimeError),
        )
        bot = SimpleNamespace(
            settings=self.settings,
            database=SimpleNamespace(pool=None),
            get_channel=lambda _: channel,
        )
        state = SimpleNamespace(
            get=AsyncMock(return_value={"channel_id": channel.id, "message_id": 10}),
            put=AsyncMock(),
        )
        with patch("justice.services.panels.StateRepository", return_value=state):
            with self.assertRaises(RuntimeError):
                await publish_panel(bot, "birthday", move_to_bottom=True)
        old.delete.assert_not_awaited()
        state.put.assert_not_awaited()

    async def test_startup_refreshes_saved_panels_only(self):
        state = SimpleNamespace(
            get=AsyncMock(
                side_effect=lambda guild, namespace, key: (
                    {"message_id": 10} if key in ("birthday", "promotion") else None
                )
            ),
        )
        bot = SimpleNamespace(
            settings=self.settings,
            database=SimpleNamespace(pool=None),
            get_cog=lambda _: None,
        )
        with (
            patch("justice.services.panels.StateRepository", return_value=state),
            patch("justice.services.panels.refresh_panel", new_callable=AsyncMock) as refresh,
        ):
            await refresh_saved_panels(bot)
        self.assertEqual(
            [call.args[1] for call in refresh.await_args_list], ["promotion", "birthday"]
        )
