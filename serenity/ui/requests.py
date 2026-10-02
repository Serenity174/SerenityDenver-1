import logging

import discord

from serenity.config import get_settings
from serenity.services.workflows import can_review, resolve_request
from serenity.ui.base import Modal, View, reply

log = logging.getLogger(__name__)


async def handle_decision(interaction, request_id, accepted, reason=""):
    await interaction.response.defer(ephemeral=True)
    try:
        row, changed = await resolve_request(interaction, request_id, accepted, reason)
    except (ValueError, PermissionError) as exc:
        return await reply(interaction, str(exc))
    status = "Одобрено" if row["status"] == "accepted" else "Отклонено"
    if row["message_id"]:
        channel = interaction.client.get_channel(
            row["channel_id"]
        ) or await interaction.client.fetch_channel(row["channel_id"])
        try:
            message = await channel.fetch_message(row["message_id"])
            embed = (
                message.embeds[0]
                if message.embeds
                else discord.Embed(title=f"Заявка #{request_id}")
            )
            embed.color = (
                discord.Color.green() if row["status"] == "accepted" else discord.Color.red()
            )
            await message.edit(
                content=f"{status} · <@{row['user_id']}> · рассмотрел <@{row['handled_by']}>",
                embed=embed,
                view=None,
            )
        except discord.NotFound:
            log.info("Request message deleted: %s", request_id)
    if changed:
        user = interaction.client.get_user(row["user_id"]) or await interaction.client.fetch_user(
            row["user_id"]
        )
        text = f"Ваша заявка #{request_id}: {status.lower()}."
        if row["kind"] == "application" and accepted:
            text += f" Обратитесь к старшему составу в <#{get_settings().accept_channel_id}>."
        if reason:
            text += f" Причина: {reason}"
        try:
            await user.send(text)
        except discord.HTTPException:
            log.info("Request DM unavailable user=%s", row["user_id"])
    await reply(
        interaction, f"{status}." if changed else f"Заявка уже обработана: {status.lower()}."
    )


class RejectModal(Modal, title="Причина отказа"):
    reason = discord.ui.TextInput(
        label="Причина", style=discord.TextStyle.paragraph, max_length=500
    )

    def __init__(self, request_id):
        super().__init__()
        self.request_id = request_id

    async def on_submit(self, interaction):
        await handle_decision(interaction, self.request_id, False, self.reason.value)


class RequestView(View):
    def __init__(self, request_id):
        super().__init__(timeout=None)
        self.request_id = request_id
        self.accept.custom_id = f"request:accept:{request_id}"
        self.reject.custom_id = f"request:reject:{request_id}"

    async def interaction_check(self, interaction):
        if not can_review(interaction.user):
            await reply(interaction, "Нет прав на рассмотрение заявки.")
            return False
        return True

    @discord.ui.button(
        label="Одобрить", style=discord.ButtonStyle.success, custom_id="request:accept"
    )
    async def accept(self, interaction, button):
        await handle_decision(interaction, self.request_id, True)

    @discord.ui.button(
        label="Отказать", style=discord.ButtonStyle.danger, custom_id="request:reject"
    )
    async def reject(self, interaction, button):
        await interaction.response.send_modal(RejectModal(self.request_id))
