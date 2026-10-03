import asyncio

import discord

from serenity.repositories.state import StateRepository
from serenity.services.settings import option

PANEL_LABELS = {
    "reports": "Отчёты",
    "application": "Вступление",
    "promotion": "Повышение",
    "vacation": "Отпуск",
    "birthday": "Дни рождения",
    "bonus": "Бонусы",
}
_locks = {}


async def publish_panel(bot, key):
    from serenity.cogs.applications import ApplicationView
    from serenity.cogs.birthday import BirthdayView
    from serenity.cogs.bonus import PromoButton
    from serenity.cogs.Otpysk import VacationButtons
    from serenity.cogs.promotion import PromotionView
    from serenity.cogs.report_db import DBReportView

    settings = bot.settings
    definitions = {
        "reports": (
            settings.report_interface_channel_id,
            option("report_title", "Отчёт по складу"),
            option("report_text", "Выберите категорию и приложите доказательство."),
            DBReportView(bot.database.pool),
            option("report_image"),
        ),
        "application": (
            settings.submit_channel_id,
            option("application_title", "Вступление в Serenity"),
            option(
                "application_text", "Ответьте на вопросы и ожидайте рассмотрения старшим составом."
            ),
            ApplicationView(),
            option("application_image"),
        ),
        "promotion": (
            settings.promotion_channel_id,
            option("promotion_title", "Заявка на повышение"),
            option("promotion_text", "Проверьте выполнение условий и приложите доказательства."),
            PromotionView(),
            None,
        ),
        "vacation": (
            settings.vacation_channel_id,
            option("vacation_title", "Оформление отпуска"),
            option(
                "vacation_text",
                "Укажите период и причину. По возвращении снимите роль кнопкой ниже.",
            ),
            VacationButtons(),
            None,
        ),
        "birthday": (
            settings.birthday_channel_id,
            option("birthday_title", "Укажите дату рождения"),
            "Заполните дату и пожелания.",
            BirthdayView(),
            None,
        ),
        "bonus": (
            settings.bonus_channel_id,
            option("bonus_title"),
            option("bonus_text"),
            PromoButton(),
            option("bonus_image"),
        ),
    }
    channel_id, title, text, view, image = definitions[key]
    async with _locks.setdefault((settings.guild_id, key), asyncio.Lock()):
        channel = bot.get_channel(channel_id) or await bot.fetch_channel(channel_id)
        embed = discord.Embed(
            title=title, description=text, color=discord.Color.from_rgb(255, 255, 255)
        )
        embed.set_footer(text=f"Панель Serenity: {key}")
        if image:
            embed.set_image(url=image)
        state = StateRepository(bot.database.pool)
        saved = await state.get(settings.guild_id, "managed_panels", key)
        message = None
        if saved and saved["channel_id"] == channel_id:
            try:
                message = await channel.fetch_message(saved["message_id"])
            except discord.NotFound:
                pass
        if message is None:
            legacy_ids = {
                "reports": "db_main_button",
                "application": "submit_application",
                "promotion": "submit_report_button",
                "vacation": "vacation_request",
                "birthday": "birthday_button",
                "bonus": "promo:get_bonus",
            }
            # Recover a send whose subsequent DB write was interrupted.
            async for candidate in channel.history(limit=100):
                if candidate.author.id == bot.user.id and (
                    candidate.embeds
                    and candidate.embeds[0].footer.text == f"Панель Serenity: {key}"
                    or any(
                        getattr(component, "custom_id", None) == legacy_ids[key]
                        for row in candidate.components
                        for component in row.children
                    )
                ):
                    message = candidate
                    break
        if message is None:
            message = await channel.send(embed=embed, view=view)
        else:
            await message.edit(embed=embed, view=view)
        await state.put(
            settings.guild_id,
            "managed_panels",
            key,
            {"channel_id": channel_id, "message_id": message.id},
        )
        if saved and saved["channel_id"] != channel_id:
            try:
                previous_channel = bot.get_channel(saved["channel_id"]) or await bot.fetch_channel(
                    saved["channel_id"]
                )
                previous = await previous_channel.fetch_message(saved["message_id"])
                await previous.edit(view=None)
            except (discord.NotFound, discord.Forbidden):
                pass
        return message
