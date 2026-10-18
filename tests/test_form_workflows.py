import unittest
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import discord

from justice.config import get_settings
from justice.services.settings import set_live


class FormWorkflowTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        set_live(None)
        self.settings = get_settings()
        self.channel = SimpleNamespace(id=55, send=AsyncMock())
        self.member = SimpleNamespace(id=44, mention="<@44>", add_roles=AsyncMock())
        self.client = SimpleNamespace(get_channel=lambda _: self.channel)
        self.interaction = SimpleNamespace(
            guild_id=self.settings.guild_id,
            guild=SimpleNamespace(get_role=lambda _: SimpleNamespace(id=33)),
            id=66,
            data={},
            user=self.member,
            client=self.client,
            response=SimpleNamespace(defer=AsyncMock(), is_done=lambda: True),
            followup=SimpleNamespace(send=AsyncMock()),
        )

    async def test_birthday_submission_moves_whole_panel_after_record(self):
        from justice.cogs.birthday import BirthdayModal

        modal = BirthdayModal()
        modal.birthday._value = "12.07"
        modal.wish._value = "Test"
        with (
            patch(
                "justice.cogs.birthday.get_database",
                return_value=SimpleNamespace(pool=SimpleNamespace(execute=AsyncMock())),
            ),
            patch("justice.services.panels.refresh_panel", new_callable=AsyncMock) as refresh,
        ):
            await modal.on_submit(self.interaction)
        self.channel.send.assert_awaited_once()
        refresh.assert_awaited_once_with(self.client, "birthday")

    async def test_family_acceptance_grants_member_roles_and_rejects_reviewer_roles(self):
        from dataclasses import replace

        from justice.services.workflows import resolve_request

        for unsafe in (False, True):
            with self.subTest(unsafe=unsafe):
                settings = replace(
                    self.settings,
                    application_role_ids=self.settings.staff_role_ids
                    if unsafe
                    else (1495255224158519409, 1495255217825124442),
                )
                row = {
                    "id": 7,
                    "guild_id": settings.guild_id,
                    "user_id": self.member.id,
                    "kind": "application",
                    "status": "pending",
                    "payload": {},
                }
                conn = SimpleNamespace(execute=AsyncMock())

                @asynccontextmanager
                async def locked(_):
                    yield conn, row

                repo = SimpleNamespace(
                    locked=locked, finish=AsyncMock(), get=AsyncMock(return_value=row)
                )
                self.member.add_roles.reset_mock()
                self.interaction.guild.get_member = lambda _: self.member
                self.interaction.guild.get_role = lambda uid: SimpleNamespace(id=uid)
                with (
                    patch("justice.services.workflows.get_settings", return_value=settings),
                    patch("justice.services.workflows.can_review", return_value=True),
                    patch("justice.services.workflows.RequestRepository", return_value=repo),
                ):
                    if unsafe:
                        with self.assertRaises(ValueError):
                            await resolve_request(self.interaction, 7, True)
                        self.member.add_roles.assert_not_awaited()
                        repo.finish.assert_not_awaited()
                    else:
                        await resolve_request(self.interaction, 7, True)
                        self.assertEqual(
                            [role.id for role in self.member.add_roles.call_args.args],
                            [1495255224158519409, 1495255217825124442],
                        )

    async def test_vacation_submission_refreshes_panel_after_publication(self):
        from justice.cogs.Otpysk import VacationModal

        @asynccontextmanager
        async def locked(_):
            yield None, {"status": "pending"}

        repo = SimpleNamespace(
            create=AsyncMock(return_value=({"id": 7}, True)),
            locked=locked,
            attach_message=AsyncMock(),
        )
        self.channel.send.return_value = SimpleNamespace(id=77)
        modal = VacationModal()
        modal.period._value = "01.01 - 12.01"
        modal.reason._value = "Test"
        with (
            patch("justice.cogs.Otpysk.RequestRepository", return_value=repo),
            patch("justice.services.panels.refresh_panel", new_callable=AsyncMock) as refresh,
        ):
            await modal.on_submit(self.interaction)
        repo.attach_message.assert_awaited_once_with(7, self.channel.id, 77)
        refresh.assert_awaited_once_with(self.client, "vacation")

    async def test_requests_refresh_their_source_panels(self):
        from justice.services.workflows import submit_request

        for kind, panel in (
            ("application", "application"),
            ("promotion", "promotion"),
            ("name_change", "promotion"),
            ("bonus", "bonus"),
        ):
            repo = SimpleNamespace(create=AsyncMock(return_value=({"id": 7}, True)))
            with (
                patch("justice.services.workflows.RequestRepository", return_value=repo),
                patch(
                    "justice.services.workflows.publish_request", new_callable=AsyncMock
                ) as publish,
                patch("justice.services.panels.refresh_panel", new_callable=AsyncMock) as refresh,
            ):
                await submit_request(self.interaction, kind, {}, 55, discord.Embed(title="Test"))
            publish.assert_awaited_once_with(self.client, repo, 7, self.channel)
            refresh.assert_awaited_once_with(self.client, panel)

    async def test_bonus_form_uses_review_channel_instead_of_panel_channel(self):
        from justice.cogs.bonus import PromoModal

        modal = PromoModal()
        with patch("justice.cogs.bonus.submit_request", new_callable=AsyncMock) as submit:
            await modal.on_submit(self.interaction)
        self.assertEqual(submit.call_args.args[3], 1495255518502060183)
        self.assertNotEqual(submit.call_args.args[3], self.settings.bonus_channel_id)

    async def test_accepted_bonus_sends_requested_dm(self):
        from justice.ui.requests import handle_decision

        user = SimpleNamespace(send=AsyncMock())
        self.client.get_user = lambda _: user
        row = {"status": "accepted", "kind": "bonus", "user_id": 44, "message_id": None}
        with patch(
            "justice.ui.requests.resolve_request", new_callable=AsyncMock, return_value=(row, True)
        ):
            await handle_decision(self.interaction, 7, True)
        user.send.assert_awaited_once_with("Вам выдана награда за ввод промокода. Проверьте счёт!")

    async def test_warehouse_publication_moves_panel_after_report_delivery(self):
        from datetime import datetime, timezone

        from justice.cogs.jobs import Jobs

        async def history(**kwargs):
            for item in []:
                yield item

        self.channel.history = history
        self.client.database = SimpleNamespace(
            pool=SimpleNamespace(
                fetchrow=AsyncMock(return_value={"created_at": datetime.now(timezone.utc)})
            )
        )
        with patch("justice.services.panels.refresh_panel", new_callable=AsyncMock) as refresh:
            await Jobs(self.client).dispatch(
                {
                    "kind": "report_publication",
                    "payload": {
                        "report_id": 7,
                        "channel_id": 55,
                        "embed": discord.Embed(title="Test").to_dict(),
                    },
                }
            )
        self.channel.send.assert_awaited_once()
        refresh.assert_awaited_once_with(self.client, "reports")
