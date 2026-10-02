import logging

import discord

from serenity.config import get_settings
from serenity.repositories.requests import RequestRepository

log = logging.getLogger(__name__)


def can_review(member):
    settings = get_settings()
    return (
        isinstance(member, discord.Member)
        and member.guild.id == settings.guild_id
        and any(role.id in settings.staff_role_ids for role in member.roles)
    )


def promotion_target(member, rank_ids):
    positions = [index for index, role_id in enumerate(rank_ids) if member.get_role(role_id)]
    if not positions:
        raise ValueError("У участника нет роли семейного ранга.")
    current = max(positions)
    return rank_ids[min(current + 1, len(rank_ids) - 1)]


async def submit_request(interaction, kind, payload, channel_id, embed):
    await interaction.response.defer(ephemeral=True)
    repo = RequestRepository()
    payload = {**payload, "_embed": embed.to_dict()}
    row, created = await repo.create(
        interaction.guild_id, interaction.user.id, kind, payload, interaction.id
    )
    if not created and (row["message_id"] or row["status"] != "pending"):
        await interaction.followup.send(
            "У вас уже есть такая заявка. Ожидайте рассмотрения.", ephemeral=True
        )
        return
    channel = interaction.client.get_channel(channel_id) or await interaction.client.fetch_channel(
        channel_id
    )
    await publish_request(interaction.client, repo, row["id"], channel)
    await interaction.followup.send(
        "Заявка сохранена и отправлена на рассмотрение.", ephemeral=True
    )


async def publish_request(bot, repo, request_id, channel):
    """Serialize publication and adopt messages left by an interrupted DB commit."""
    from serenity.ui.requests import RequestView

    async with repo.locked(request_id) as (conn, row):
        if row["message_id"] or row["status"] != "pending":
            return
        found = None
        async for message in channel.history(limit=None, after=row["created_at"]):
            if (
                message.author.id == bot.user.id
                and message.embeds
                and message.embeds[0].footer.text == f"Заявка #{request_id}"
            ):
                found = message
                break
        if found is None:
            data = row["payload"].get("_embed") or row["payload"].get("legacy_embed")
            embed = (
                discord.Embed.from_dict(data)
                if data
                else discord.Embed(
                    title="Заявка на рассмотрение", description=f"<@{row['user_id']}>"
                )
            )
            embed.set_footer(text=f"Заявка #{request_id}")
            found = await channel.send(
                content=" ".join(f"<@&{role}>" for role in get_settings().staff_role_ids),
                embed=embed,
                view=RequestView(request_id),
            )
        await conn.execute(
            "UPDATE public.requests SET channel_id=$2,message_id=$3 WHERE id=$1",
            request_id,
            channel.id,
            found.id,
        )
        bot.add_view(RequestView(request_id), message_id=found.id)


async def resolve_request(interaction, request_id, accepted, reason=""):
    settings = get_settings()
    if not can_review(interaction.user):
        raise PermissionError("Нет прав на рассмотрение заявки.")
    repo = RequestRepository()
    async with repo.locked(request_id) as (conn, row):
        if row is None or row["guild_id"] != interaction.guild_id:
            raise ValueError("Заявка не найдена.")
        if row["status"] != "pending":
            return row, False
        member = interaction.guild.get_member(row["user_id"])
        if member is None:
            try:
                member = await interaction.guild.fetch_member(row["user_id"])
            except discord.NotFound:
                if accepted and row["kind"] != "bonus":
                    raise ValueError("Участник покинул сервер.") from None
        if accepted and row["kind"] == "application":
            roles = [
                interaction.guild.get_role(role_id) for role_id in settings.application_role_ids
            ]
            if any(role is None for role in roles):
                raise ValueError("Не найдены роли для принятия заявки. Проверьте настройки.")
            await member.add_roles(*roles, reason=f"Заявка #{request_id}")
        elif accepted and row["kind"] in ("promotion", "name_change"):
            # Target was saved BEFORE changing Discord roles. Retrying cannot promote twice.
            target_id = row["payload"]["target_role_id"]
            target = interaction.guild.get_role(target_id)
            if target is None or target_id not in settings.rank_role_ids:
                raise ValueError("Целевая роль больше не существует. Проверьте заявку и настройки.")
            current = [role for role in member.roles if role.id in settings.rank_role_ids]
            target_index = settings.rank_role_ids.index(target_id)
            if not any(settings.rank_role_ids.index(role.id) > target_index for role in current):
                await member.add_roles(target, reason=f"Повышение по заявке #{request_id}")
                old_roles = [role for role in current if role.id != target_id]
                if old_roles:
                    await member.remove_roles(
                        *old_roles, reason=f"Повышение по заявке #{request_id}"
                    )
        elif not accepted and row["kind"] == "application" and member:
            await member.kick(reason=reason or f"Отказ по заявке #{request_id}")
        payload = dict(row["payload"])
        payload["decision_reason"] = reason
        await conn.execute("UPDATE public.requests SET payload=$2 WHERE id=$1", request_id, payload)
        await repo.finish(
            conn, request_id, "accepted" if accepted else "rejected", interaction.user.id
        )
    return await repo.get(request_id), True
