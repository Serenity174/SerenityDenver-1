import logging

import discord

log = logging.getLogger(__name__)


async def reply(interaction, text):
    if interaction.response.is_done():
        await interaction.followup.send(text, ephemeral=True)
    else:
        await interaction.response.send_message(text, ephemeral=True)


async def interaction_error(interaction, error):
    log.error(
        "Interaction failed id=%s user=%s",
        interaction.id,
        interaction.user.id,
        exc_info=(type(error), error, error.__traceback__),
    )
    try:
        await reply(
            interaction,
            "Не удалось выполнить действие. Попробуйте ещё раз; ошибка записана в журнал.",
        )
    except discord.HTTPException:
        log.warning("Could not report interaction error id=%s", interaction.id)


class View(discord.ui.View):
    async def interaction_check(self, interaction):
        from serenity.config import get_settings

        if interaction.guild_id != get_settings().guild_id:
            await reply(interaction, "Эта форма доступна только на сервере семьи.")
            return False
        return True

    async def on_error(self, interaction, error, item):
        await interaction_error(interaction, error)


class Modal(discord.ui.Modal):
    async def on_error(self, interaction, error):
        await interaction_error(interaction, error)
