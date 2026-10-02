# -*- coding: utf-8 -*-
# giveaways.py — гивэвеи с персистентными вьюхами, счётчиком участников и тегом роли над эмбедой.
# Требуется: discord.py >= 2.3  (pip install -U discord.py)
import asyncio
import contextlib
import datetime as dt
import logging
import re
from typing import List, Optional, Sequence

import asyncpg
import discord
from discord import app_commands
from discord.ext import commands, tasks

from serenity.config import get_settings
from serenity.repositories.giveaways import (
    Giveaway,
    get_guild_settings,
    pg_choose_winners,
    pg_create_give,
    pg_due,
    pg_get_give,
    pg_get_user_ids,
    pg_list_running,
    pg_mark_ended,
    pg_mark_running,
    pg_set_message_id,
    pg_toggle_entry,
    set_guild_color,
    set_guild_emoji,
)
from serenity.repositories.jobs import JobRepository
from serenity.ui.base import View

settings = get_settings()

# === НАСТРОЙКИ ===
GUILD_ID = settings.guild_id
ROLE_TAG_ID = settings.family_role_id  # тэгнем эту роль над эмбедой

# Postgres (public.give, public.guild_settings)
DATABASE_URL = settings.database_url


# === УТИЛИТЫ ===
# поддерживаем и кириллицу, и латиницу в суффиксах: с/s, м/m, ч/h, д/d, w
DUR_RE = re.compile(r"(?P<value>\d+)\s*(?P<unit>[смчдwsmhd])", re.IGNORECASE)


def parse_duration(s: str) -> dt.timedelta:
    s = s.strip()
    if not s:
        raise ValueError("Пустая длительность")
    total = dt.timedelta()
    for m in DUR_RE.finditer(s):
        val = int(m.group("value"))
        unit = m.group("unit").lower()
        if unit in ("с", "s"):
            total += dt.timedelta(seconds=val)
        elif unit in ("м", "m"):
            total += dt.timedelta(minutes=val)
        elif unit in ("ч", "h"):
            total += dt.timedelta(hours=val)
        elif unit in ("д", "d"):
            total += dt.timedelta(days=val)
        elif unit in ("w",):
            total += dt.timedelta(weeks=val)
    if total.total_seconds() <= 0:
        raise ValueError("Неверная длительность")
    return total


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def fmt_dt(ts: dt.datetime) -> str:
    return discord.utils.format_dt(ts, style="R")


# === ДАННЫЕ (Postgres) ===

# === EMBED/VIEW ===


def emb_running(
    g: Giveaway,
    color: int,
    join_emoji: str,
    host: discord.User,
    participants: int,
    display_id: Optional[int] = None,
) -> discord.Embed:
    """
    display_id — ID, который хотим показывать в футере (например, Postgres ID).
    Если None — используется g.id.
    """
    e = discord.Embed(
        title=f"Розыгрыш: {g.prize}",
        description=(
            "Нажми кнопку ниже, чтобы участвовать.\n\n"
            f"Участников: **{participants}**\n"
            f"Завершение: {fmt_dt(g.ends_at)}\n"
            f"Хост: {host.mention}\n"
            f"Кол-во победителей: **{g.winners_count}**\n"
        ),
        color=color,
        timestamp=g.ends_at,
    )
    real_id = display_id if display_id is not None else g.id
    e.set_footer(text=f"ID: {real_id} • Участвуй: {join_emoji}")
    return e


def emb_ended(
    g: Giveaway,
    color: int,
    winners: Sequence[discord.User],
    display_id: Optional[int] = None,
) -> discord.Embed:
    winners_ment = ", ".join(w.mention for w in winners) if winners else "никто 😢"
    e = discord.Embed(
        title=f"✅ Итоги розыгрыша: {g.prize}",
        description=f"Победители: {winners_ment}",
        color=color,
        timestamp=utcnow(),
    )
    real_id = display_id if display_id is not None else g.id
    e.set_footer(text=f"ID: {real_id}")
    return e


def extract_display_id_from_embed(embed: discord.Embed) -> Optional[int]:
    """
    Вытаскиваем ID из футера вида:
        "ID: 123 • Участвуй: 🎉"
    """
    if not embed.footer or not embed.footer.text:
        return None
    text = embed.footer.text
    m = re.search(r"ID:\s*(\d+)", text)
    if not m:
        return None
    try:
        return int(m.group(1))
    except ValueError:
        return None


class JoinView(View):
    """
    Персистентная вью (timeout=None) с уникальным custom_id для каждого розыгрыша.
    Работает только с Postgres (public.give).
    """

    def __init__(self, giveaway_id: int, join_emoji: str):
        super().__init__(timeout=None)
        self.giveaway_id = giveaway_id
        self.join_emoji = join_emoji

        # Кнопка участия
        self.add_item(
            discord.ui.Button(
                label="Участвовать",
                style=discord.ButtonStyle.success,
                emoji=join_emoji,
                custom_id=f"gw:join:{giveaway_id}",
            )
        )

        # Кнопка "посмотреть участников"
        self.add_item(
            discord.ui.Button(
                label="Посмотреть участников",
                style=discord.ButtonStyle.secondary,
                custom_id=f"gw:list:{giveaway_id}",
            )
        )

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        cid = str(interaction.data.get("custom_id", "")) if interaction.data else ""
        logging.getLogger(__name__).info(
            str(f"[giveaways] interaction_check called, custom_id={cid}")
        )

        if not cid.startswith("gw:"):
            return True  # не наш кастом-айди

        # Быстро подтверждаем interaction, чтобы не протух
        if not interaction.response.is_done():
            with contextlib.suppress(discord.HTTPException):
                await interaction.response.defer(ephemeral=True)

        # --- JOIN ---
        if cid.startswith("gw:join:"):
            gid = int(cid.split(":")[-1])
            logging.getLogger(__name__).info(
                str(f"[giveaways] parsed giveaway id from button (join): {gid}")
            )

            g = await pg_get_give(gid)
            if not g or g.finished or utcnow() >= g.ends_at:
                with contextlib.suppress(discord.HTTPException):
                    await interaction.followup.send("⛔ Розыгрыш уже завершён.", ephemeral=True)
                return False

            joined, user_ids = await pg_toggle_entry(gid, interaction.user.id)

            try:
                if joined:
                    await interaction.followup.send(
                        "Ты в списке участников! Удачи 🍀", ephemeral=True
                    )
                else:
                    await interaction.followup.send("Ты вышел из розыгрыша.", ephemeral=True)
            except discord.HTTPException:
                pass

            # обновим эмбед со свежим количеством участников
            try:
                if g and interaction.message:
                    color, _ = await get_guild_settings(interaction.guild_id)
                    host = interaction.guild.get_member(
                        g.host_id
                    ) or await interaction.client.fetch_user(g.host_id)

                    participants = len(user_ids)

                    display_id = None
                    if interaction.message.embeds:
                        display_id = extract_display_id_from_embed(interaction.message.embeds[0])

                    new_embed = emb_running(
                        g, color, self.join_emoji, host, participants, display_id=display_id
                    )
                    await interaction.message.edit(embed=new_embed, view=self)
            except discord.HTTPException:
                pass

            return False

        # --- LIST PARTICIPANTS ---
        if cid.startswith("gw:list:"):
            gid = int(cid.split(":")[-1])
            logging.getLogger(__name__).info(
                str(f"[giveaways] parsed giveaway id from button (list): {gid}")
            )

            g = await pg_get_give(gid)
            if not g or g.guild_id != interaction.guild_id:
                with contextlib.suppress(discord.HTTPException):
                    await interaction.followup.send("⛔ Розыгрыш не найден.", ephemeral=True)
                return False

            ids = await pg_get_user_ids(gid)
            if not ids:
                with contextlib.suppress(discord.HTTPException):
                    await interaction.followup.send("Пока никто не участвует.", ephemeral=True)
                return False

            guild = interaction.guild
            users: List[discord.abc.User] = []
            for uid in ids:
                member = guild.get_member(uid) if guild else None
                if member is None:
                    with contextlib.suppress(Exception):
                        member = await interaction.client.fetch_user(uid)
                if member:
                    users.append(member)

            if not users:
                text = "Участников не удалось получить."
            else:
                lines = [f"{idx + 1}. {u.mention}" for idx, u in enumerate(users)]
                text = f"Участники ({len(users)}):\n" + "\n".join(lines)
                if len(text) > 1900:
                    text = text[:1900] + "\n…"

            with contextlib.suppress(discord.HTTPException):
                await interaction.followup.send(text, ephemeral=True)

            return False

        return True


# === COG ===
class Giveaways(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._end_locks = {}
        self._tick.start()

    def cog_unload(self):
        self._tick.cancel()

    @tasks.loop(seconds=15)
    async def _tick(self):
        await self.bot.wait_until_ready()

        # End due giveaways (with delay between each to avoid rate limits)
        try:
            due_giveaways = await pg_due()
        except (asyncpg.PostgresError, TimeoutError, OSError) as e:
            logging.getLogger(__name__).info(str(f"[giveaways] pg_due failed: {e}"))
            return
        for i, g in enumerate(due_giveaways):
            try:
                await self._end_and_announce(g)
                # Пауза между гивэвеями чтобы избежать rate limit
                if i < len(due_giveaways) - 1:
                    await asyncio.sleep(3)
            except Exception as e:
                logging.getLogger(__name__).info(str(f"[giveaways] failed to end {g.id}: {e}"))

    async def _end_and_announce(self, g):
        lock = self._end_locks.setdefault(g.id, asyncio.Lock())
        async with lock:
            g = await pg_get_give(g.id)
            if g is None or g.finished:
                return
            guild = self.bot.get_guild(g.guild_id)
            if guild is None:
                raise RuntimeError("Giveaway guild unavailable")
            channel = guild.get_channel(g.channel_id) or await guild.fetch_channel(g.channel_id)
            color, _ = await get_guild_settings(g.guild_id)
            ids, version = await pg_choose_winners(g.id)
            winners = []
            for user_id in ids:
                try:
                    winners.append(guild.get_member(user_id) or await self.bot.fetch_user(user_id))
                except discord.NotFound:
                    continue
            embed = emb_ended(g, color, winners)
            try:
                message = await channel.fetch_message(g.message_id)
                await message.edit(embed=embed, view=None)
            except discord.NotFound:
                message = await channel.send(embed=embed)
                await pg_set_message_id(g.id, message.id)
            now = utcnow()
            for winner in winners:
                await JobRepository().schedule(
                    "dm",
                    f"giveaway:{g.id}:{version}:{winner.id}",
                    {
                        "user_id": winner.id,
                        "content": f"🎉 Ты выиграл(а) **{g.prize}** на сервере **{guild.name}**! (ID: {g.id})",
                    },
                    now,
                    now + dt.timedelta(days=2),
                )
            await pg_mark_ended(g.id)

    # === СЛЭШ-КОМАНДЫ (РУС) ===

    @app_commands.command(name="розыгрыш", description="Запустить розыгрыш")
    @app_commands.describe(
        длительность="Например: 30м, 2ч, 1д или составное: 1ч30м",
        победителей="Количество победителей (1–50)",
        приз="Что разыгрывается",
    )
    @app_commands.checks.has_role(get_settings().high_staff_role_id)
    async def cmd_start(
        self,
        itx: discord.Interaction,
        длительность: str,
        победителей: app_commands.Range[int, 1, 50],
        приз: str,
    ):
        # Сразу скрыто подтверждаем interaction, чтобы не протух
        await itx.response.defer(ephemeral=True, thinking=True)

        try:
            delta = parse_duration(длительность)
        except ValueError:
            return await itx.followup.send(
                "⛔ Неверная длительность. Примеры: 30м, 2ч, 1д, 1ч30м", ephemeral=True
            )

        ends = utcnow() + delta

        # создаём запись в БД (без message_id)
        gid = await pg_create_give(
            guild_id=itx.guild_id,
            channel_id=itx.channel_id,
            prize=приз,
            winners=победителей,
            ends_at=ends,
            host_id=itx.user.id,
        )

        g = await pg_get_give(gid)
        if not g:
            return await itx.followup.send("⛔ Не удалось создать розыгрыш.", ephemeral=True)

        color, emoji = await get_guild_settings(itx.guild_id)
        view = JoinView(gid, emoji)
        participants = 0

        # Отправляем основное сообщение о розыгрыше в канал
        msg = await itx.channel.send(
            content=f"<@&{ROLE_TAG_ID}>",
            embed=emb_running(g, color, emoji, itx.user, participants, display_id=gid),
            view=view,
            allowed_mentions=discord.AllowedMentions(roles=True, users=False, everyone=False),
        )

        # обновляем message_id в БД
        await pg_set_message_id(gid, msg.id)

        # регистрируем персистентную вью
        self.bot.add_view(view)

        # и даём пользователю тихий ответ
        await itx.followup.send(f"✅ Розыгрыш **#{gid}** создан.", ephemeral=True)

    @app_commands.command(name="завершить", description="Завершить розыгрыш по ID")
    @app_commands.describe(id="ID розыгрыша")
    @app_commands.checks.has_role(get_settings().high_staff_role_id)
    async def cmd_end(self, itx: discord.Interaction, id: int):
        # сначала скрыто подтверждаем interaction
        await itx.response.defer(ephemeral=True, thinking=True)

        g = await pg_get_give(id)
        if not g or g.guild_id != itx.guild_id:
            return await itx.followup.send("⛔ Розыгрыш не найден.", ephemeral=True)
        if g.finished:
            return await itx.followup.send("ℹ️ Уже завершён.", ephemeral=True)

        await self._end_and_announce(g)
        await itx.followup.send("✅ Завершено.", ephemeral=True)

    @app_commands.command(name="переролл", description="Перероллить победителей по ID")
    @app_commands.describe(id="ID розыгрыша (уже завершённого)")
    @app_commands.checks.has_role(get_settings().high_staff_role_id)
    async def cmd_reroll(self, itx: discord.Interaction, id: int):
        # сразу скрыто подтверждаем interaction, чтобы не получить Unknown interaction
        await itx.response.defer(ephemeral=True, thinking=True)

        g = await pg_get_give(id)
        if not g or g.guild_id != itx.guild_id:
            return await itx.followup.send("⛔ Розыгрыш не найден.", ephemeral=True)
        if not g.finished:
            return await itx.followup.send("⛔ Сначала завершите розыгрыш.", ephemeral=True)

        # делаем его снова "running"
        await pg_mark_running(g.id)
        # читаем обновлённый (finished=False)
        g = await pg_get_give(g.id)

        await self._end_and_announce(g)
        await itx.followup.send("🔁 Переролл выполнен.", ephemeral=True)

    @app_commands.command(name="список", description="Показать активные розыгрыши")
    async def cmd_list(self, itx: discord.Interaction):
        items = await pg_list_running(itx.guild_id)
        if not items:
            return await itx.response.send_message("Пока активных розыгрышей нет.", ephemeral=True)
        lines = []
        for g in items:
            ch = itx.guild.get_channel(g.channel_id) if itx.guild else None
            ch_text = ch.mention if isinstance(ch, discord.abc.GuildChannel) else f"#{g.channel_id}"
            lines.append(
                f"**ID {g.id}** • {ch_text} • {g.prize} • "
                f"победителей: **{g.winners_count}** • завершение {fmt_dt(g.ends_at)}"
            )
        await itx.response.send_message("\n".join(lines), ephemeral=True)

    # группа настроек
    settings = app_commands.Group(
        name="настройки_розыгрыша", description="Настроить внешний вид и эмодзи"
    )

    @settings.command(name="показать", description="Показать текущие настройки")
    async def cmd_settings_show(self, itx: discord.Interaction):
        color, emoji = await get_guild_settings(itx.guild_id)
        e = discord.Embed(title="Настройки розыгрышей", color=color)
        e.add_field(name="Цвет эмбеда", value=f"#{color:06X}")
        e.add_field(name="Эмодзи кнопки", value=emoji)
        await itx.response.send_message(embed=e, ephemeral=True)

    @settings.command(name="изменить", description="Изменить цвет эмбеда или эмодзи кнопки участия")
    @app_commands.describe(цвет_hex="HEX без #, напр. FFCC00", эмодзи="Эмодзи кнопки участия")
    @app_commands.checks.has_role(get_settings().high_staff_role_id)
    async def cmd_settings_set(
        self, itx: discord.Interaction, цвет_hex: Optional[str] = None, эмодзи: Optional[str] = None
    ):
        if not цвет_hex and not эмодзи:
            return await itx.response.send_message(
                "Укажи хотя бы один параметр: цвет_hex или эмодзи.", ephemeral=True
            )
        try:
            if цвет_hex:
                await set_guild_color(itx.guild_id, цвет_hex)
            if эмодзи:
                await set_guild_emoji(itx.guild_id, эмодзи)
        except Exception as e:
            return await itx.response.send_message(f"⛔ {e}", ephemeral=True)
        await itx.response.send_message("✅ Обновлено.", ephemeral=True)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return interaction.guild is not None

    async def cog_load(self):
        logging.getLogger(__name__).info(str("[giveaways] cog_load called"))
        guild_obj = discord.Object(id=GUILD_ID)

        # регистрируем команды на конкретную гильдию
        self.bot.tree.add_command(self.cmd_start, guild=guild_obj)
        self.bot.tree.add_command(self.cmd_end, guild=guild_obj)
        self.bot.tree.add_command(self.cmd_reroll, guild=guild_obj)
        self.bot.tree.add_command(self.cmd_list, guild=guild_obj)
        self.bot.tree.add_command(self.settings, guild=guild_obj)

        # при загрузке — восстановим только персистентные вьюхи
        # просроченные гивэвеи обработает _tick через 15 сек (избегаем rate limit)
        try:
            _, emoji = await get_guild_settings(GUILD_ID)
            running = await pg_list_running(GUILD_ID)
            logging.getLogger(__name__).info(
                str(f"[giveaways] running giveaways on load: {[g.id for g in running]}")
            )
            for g in running:
                logging.getLogger(__name__).info(str(f"[giveaways] add_view for giveaway {g.id}"))
                self.bot.add_view(JoinView(g.id, emoji))
        except Exception as e:
            logging.getLogger(__name__).info(str("Persistent views restore failed:") + " " + str(e))


async def setup(bot: commands.Bot):
    await bot.add_cog(Giveaways(bot))
