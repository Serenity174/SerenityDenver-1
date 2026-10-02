import asyncio
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

import asyncpg
import discord
from discord import Interaction, app_commands
from discord.ext import commands, tasks

from serenity.config import get_settings
from serenity.repositories.contracts import ContractDB
from serenity.ui.base import View

settings = get_settings()


CONTRACT_CHANNEL_ID = settings.contract_channel_id
GUILD_ID = settings.guild_id

MAX_ACTIVE_SLOTS = 5  # including host

ROLE_PRIORITY: Dict[int, int] = {
    role_id: rank for rank, role_id in enumerate(settings.rank_role_ids, start=1)
}
# High Staff has lower priority than the numbered ranks.
ROLE_PRIORITY[settings.high_staff_role_id] = len(settings.rank_role_ids) + 1

HIGH_STAFF_ROLE_ID = settings.high_staff_role_id
VERIFIED_ROLE_ID = settings.verified_role_id


class RemoveUserSelect(discord.ui.Select):
    def __init__(
        self,
        cog: "ContractsCog",
        contract_id: int,
        contract_message: discord.Message,
        options: List[discord.SelectOption],
    ):
        super().__init__(
            placeholder="Выбери кого убрать", options=options, min_values=1, max_values=1
        )
        self.cog = cog
        self.contract_id = contract_id
        self.contract_message = contract_message

    async def callback(self, interaction: Interaction):
        user_id = int(self.values[0])
        await self.cog.db.connect()
        async with self.cog._get_lock(self.contract_id):
            contract = await self.cog.db.get_contract_by_message(self.contract_message.id)
            if not contract or not (
                self.cog._is_high_staff(interaction.user)
                or contract["host_id"] == interaction.user.id
            ):
                return await self.cog._ephemeral(interaction, "Нет прав управлять этой записью.")
            if contract and int(contract["host_id"]) == user_id:
                return await interaction.response.send_message(
                    "Хоста нельзя удалить из записи.", ephemeral=True
                )
            await self.cog.db.remove_signup(self.contract_id, user_id)
            updated = await self.cog.db.get_contract_by_message(self.contract_message.id)
            if updated:
                await self.cog._refresh_message(self.contract_message, updated)
        await interaction.response.send_message(f"Убрали <@{user_id}> из записи.", ephemeral=True)


class RemoveUserView(View):
    def __init__(
        self, cog: "ContractsCog", contract_id: int, contract_message: discord.Message, signups
    ):
        super().__init__(timeout=120)
        options: List[discord.SelectOption] = []
        guild = cog.bot.get_guild(GUILD_ID)
        for idx, row in enumerate(signups[:25]):  # Discord select limit
            member = guild.get_member(row["user_id"]) if guild else None
            label = member.display_name if member else str(row["user_id"])
            options.append(
                discord.SelectOption(
                    label=label[:100],
                    description=f"#{idx + 1} id:{row['user_id']}",
                    value=str(row["user_id"]),
                )
            )
        self.add_item(RemoveUserSelect(cog, contract_id, contract_message, options))


class ContractCloseConfirmView(View):
    def __init__(self, cog: "ContractsCog", contract_id: int, contract_message: discord.Message):
        super().__init__(timeout=60)
        self.cog = cog
        self.contract_id = contract_id
        self.contract_message = contract_message

    @discord.ui.button(
        label="Подтвердить", style=discord.ButtonStyle.danger, custom_id="contract_close_confirm"
    )
    async def confirm(self, interaction: Interaction, _: discord.ui.Button):
        if not await self.cog._ensure_deferred(interaction):
            return

        await self.cog.db.connect()
        async with self.cog._get_lock(self.contract_id):
            contract = await self.cog.db.get_contract_by_message(self.contract_message.id)
            if not contract or not (
                self.cog._is_high_staff(interaction.user)
                or contract["host_id"] == interaction.user.id
            ):
                return await self.cog._ephemeral(interaction, "Нет прав управлять этой записью.")
            if not contract:
                return await self.cog._ephemeral(interaction, "Запись не найдена.")

            if contract["closed"]:
                await self.cog._refresh_message(self.contract_message, contract)
                return await self.cog._ephemeral(interaction, "Запись уже закрыта.")

            await self.cog.db.close_contract(self.contract_id)
            updated = await self.cog.db.get_contract_by_message(self.contract_message.id)
            await self.cog._refresh_message(self.contract_message, updated)

        await interaction.edit_original_response(view=None)
        await self.cog._ephemeral(interaction, "Запись закрыта. Участники зафиксированы.")

    @discord.ui.button(
        label="Отмена", style=discord.ButtonStyle.secondary, custom_id="contract_close_cancel"
    )
    async def cancel(self, interaction: Interaction, _: discord.ui.Button):
        if interaction.response.is_done():
            await interaction.edit_original_response(content="Закрытие отменено.", view=None)
        else:
            await interaction.response.edit_message(content="Закрытие отменено.", view=None)
        self.stop()


class ContractOpenView(View):
    def __init__(self, cog: "ContractsCog"):
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.button(
        label="➕", style=discord.ButtonStyle.secondary, custom_id="contract_join", row=0
    )
    async def join(self, interaction: Interaction, _: discord.ui.Button):
        await self.cog.handle_join(interaction)

    @discord.ui.button(
        label="➖", style=discord.ButtonStyle.secondary, custom_id="contract_leave", row=0
    )
    async def leave(self, interaction: Interaction, _: discord.ui.Button):
        await self.cog.handle_leave(interaction)

    @discord.ui.button(
        label="👤", style=discord.ButtonStyle.secondary, custom_id="contract_remove_user", row=0
    )
    async def remove_user(self, interaction: Interaction, _: discord.ui.Button):
        await self.cog.handle_remove_user(interaction)

    @discord.ui.button(
        label="Удалить кнопки", style=discord.ButtonStyle.danger, custom_id="contract_close", row=1
    )
    async def close(self, interaction: Interaction, _: discord.ui.Button):
        await self.cog.handle_close(interaction)


class AttendanceView(View):
    def __init__(self, cog: "ContractsCog"):
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.button(
        label="Отметить явку всем", style=discord.ButtonStyle.primary, custom_id="contract_mark"
    )
    async def mark_all(self, interaction: Interaction, _: discord.ui.Button):
        await self.cog.handle_mark_all(interaction)


class ContractsCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = ContractDB(bot.database.pool)
        self._locks: Dict[int, asyncio.Lock] = {}
        self.weekly_reset_task.start()

    def cog_unload(self):
        self.weekly_reset_task.cancel()

    # ------------ Helpers ------------ #

    def _get_lock(self, contract_id: int) -> asyncio.Lock:
        if contract_id not in self._locks:
            self._locks[contract_id] = asyncio.Lock()
        return self._locks[contract_id]

    def _get_rank_from_member(self, member: discord.Member) -> int:
        ranks: List[int] = []
        for role in member.roles:
            if role.id in ROLE_PRIORITY:
                ranks.append(ROLE_PRIORITY[role.id])
        return min(ranks) if ranks else 999

    def _format_rank(self, rank: int) -> str:
        if rank == ROLE_PRIORITY.get(HIGH_STAFF_ROLE_ID):
            return "High Staff"
        if rank == 999:
            return "нет ранга"
        return str(rank)

    def _is_high_staff(self, member: discord.Member) -> bool:
        return any(r.id == HIGH_STAFF_ROLE_ID for r in member.roles)

    def _has_contract_access(self, member: discord.Member) -> bool:
        return self._is_high_staff(member) or any(r.id == VERIFIED_ROLE_ID for r in member.roles)

    async def _ephemeral(self, interaction: Interaction, content: str):
        if not interaction.response.is_done():
            try:
                await interaction.response.defer(ephemeral=True)
            except discord.NotFound:
                return
        try:
            await interaction.followup.send(content, ephemeral=True)
        except discord.NotFound:
            return

    async def _ensure_deferred(self, interaction: Interaction) -> bool:
        """
        Быстро подтверждаем взаимодействие, чтобы избежать Unknown interaction (10062),
        если дальнейшая работа (БД, сеть) затянется дольше 3 секунд.
        """
        if interaction.response.is_done():
            return True
        try:
            await interaction.response.defer(ephemeral=True)
            return True
        except discord.NotFound:
            return False

    def _build_embed(
        self,
        contract: asyncpg.Record,
        signups: List[asyncpg.Record],
    ) -> discord.Embed:
        status_parts = []
        if contract["attendance_marked"]:
            status_parts.append("Явка отмечена")
        elif contract["closed"]:
            status_parts.append("Закрыт")
        else:
            status_parts.append("Открыт")

        title = "Контракт"
        embed = discord.Embed(
            title=title,
            description=f"Статус: {', '.join(status_parts)}",
            color=discord.Color.from_rgb(255, 255, 255),
            timestamp=contract["created_at"],
        )

        host_id = int(contract["host_id"])
        host_line = f"1. <@{host_id}> (хост)"

        main_lines: List[str] = [host_line]
        wait_lines: List[str] = []
        slot_number = 2
        for row in signups:
            if int(row["user_id"]) == host_id:
                continue
            line = (
                f"{slot_number}. <@{row['user_id']}> "
                f"(ранг {self._format_rank(row['rank'])}, нед.явок {row['weekly_attendance']})"
            )
            slot_number += 1
            if len(main_lines) < MAX_ACTIVE_SLOTS:
                main_lines.append(line)
            else:
                wait_lines.append(line)

        embed.add_field(
            name=f"Состав (до {MAX_ACTIVE_SLOTS})",
            value="\n".join(main_lines) if main_lines else "Пока пусто",
            inline=False,
        )
        embed.add_field(
            name="Лист ожидания",
            value="\n".join(wait_lines) if wait_lines else "Никого",
            inline=False,
        )

        embed.set_footer(text="Очередь: ранг ↑, недельные явки ↑, время записи ↑")
        return embed

    async def _get_contract_from_message(
        self, message: discord.Message
    ) -> Tuple[Optional[int], Optional[asyncpg.Record]]:
        contract = await self.db.get_contract_by_message(message.id)
        if not contract:
            return None, None
        return int(contract["id"]), contract

    async def _refresh_message(self, message: discord.Message, contract: asyncpg.Record):
        signups = await self.db.fetch_signups(int(contract["id"]), bool(contract["closed"]))
        embed = self._build_embed(contract, signups)
        view: Optional[discord.ui.View]

        if contract["attendance_marked"]:
            view = None
        elif contract["closed"]:
            view = AttendanceView(self)
        else:
            view = ContractOpenView(self)

        await message.edit(embed=embed, view=view)

    # ------------ Slash commands ------------ #

    @app_commands.command(name="основа", description="Создать запись на контракт")
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def create_contract(self, interaction: Interaction):
        if not isinstance(interaction.user, discord.Member) or not self._is_high_staff(
            interaction.user
        ):
            return await interaction.response.send_message(
                "Нет прав для создания контракта.", ephemeral=True
            )

        await interaction.response.defer(ephemeral=True, thinking=True)

        channel = interaction.guild.get_channel(CONTRACT_CHANNEL_ID) if interaction.guild else None
        if not channel or not isinstance(channel, discord.TextChannel):
            return await interaction.followup.send(
                "Канал для контрактов не найден.", ephemeral=True
            )

        await self.db.connect()
        host_rank = self._get_rank_from_member(interaction.user)
        await self.db.upsert_user(interaction.user.id, host_rank)

        embed = self._build_embed(
            contract={
                "host_id": interaction.user.id,
                "closed": False,
                "attendance_marked": False,
                "created_at": datetime.now(timezone.utc),
            },
            signups=[
                {
                    "user_id": interaction.user.id,
                    "rank": host_rank,
                    "weekly_attendance": 0,
                    "total_attendance": 0,
                    "created_at": datetime.now(timezone.utc),
                }
            ],
        )

        view = ContractOpenView(self)
        message = await channel.send(embed=embed, view=view)
        contract_id = await self.db.create_contract(channel.id, message.id, interaction.user.id)
        await self.db.add_signup(contract_id, interaction.user.id)
        contract = await self.db.get_contract_by_message(message.id)
        if contract:
            await self._refresh_message(message, contract)
        await interaction.followup.send(
            f"Контракт создан в {channel.mention} (ID: {contract_id}).", ephemeral=True
        )

    @app_commands.command(name="профиль", description="Показать статистику явок пользователя")
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    @app_commands.default_permissions()
    @app_commands.describe(user="Кого показать")
    async def profile(self, interaction: Interaction, user: Optional[discord.Member] = None):
        target = user or interaction.user
        await self.db.connect()
        profile = await self.db.fetch_profile(target.id)
        if not profile:
            return await interaction.response.send_message(
                "Данных по этому пользователю нет.", ephemeral=True
            )

        embed = discord.Embed(
            title="Статистика явок",
            description=f"{target.mention}",
            color=discord.Color.from_rgb(255, 255, 255),
            timestamp=datetime.now(timezone.utc),
        )
        embed.add_field(
            name="Ранг (приоритет)",
            value=self._format_rank(profile["rank"]),
            inline=True,
        )
        embed.add_field(name="Недельных явок", value=str(profile["weekly_attendance"]), inline=True)
        embed.add_field(name="Всего явок", value=str(profile["total_attendance"]), inline=True)
        last_attended = profile["last_attended_at"]
        embed.add_field(
            name="Последняя явка",
            value=last_attended.strftime("%d.%m.%Y %H:%M") if last_attended else "Нет данных",
            inline=False,
        )

        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(
        name="сброс_контрактов",
        description="Очистить контракты и обнулить явки (только High Staff)",
    )
    @app_commands.guilds(discord.Object(id=GUILD_ID))
    async def reset_contracts(self, interaction: Interaction):
        if not isinstance(interaction.user, discord.Member) or not self._is_high_staff(
            interaction.user
        ):
            return await interaction.response.send_message("Недостаточно прав.", ephemeral=True)

        # Быстро подтверждаем, чтобы избежать timeout взаимодействия
        await interaction.response.defer(ephemeral=True)

        updated_count = await self.db.reset_all()

        await interaction.followup.send(
            f"Контракты очищены, явки пользователей обнулены. Затронуто пользователей: {updated_count}.",
            ephemeral=True,
        )

    # ------------ Button handlers ------------ #

    async def handle_join(self, interaction: Interaction):
        if not interaction.message:
            return
        if not await self._ensure_deferred(interaction):
            return
        contract_id, contract = await self._get_contract_from_message(interaction.message)
        if not contract:
            return await self._ephemeral(interaction, "Контракт не найден.")

        if contract["closed"]:
            return await self._ephemeral(interaction, "Контракт закрыт.")

        if not isinstance(interaction.user, discord.Member):
            return await self._ephemeral(interaction, "Только участники сервера могут записаться.")

        if not self._has_contract_access(interaction.user):
            return await self._ephemeral(
                interaction,
                (
                    "Вы не подтвердили свой уровень.\n"
                    f"Запись на контракт доступна только тем, кто отправил скриншот из F2 - Персонаж-Статистика в канал канал <#{CONTRACT_CHANNEL_ID}>.\n"
                    f"После того, как Вы получите роль <@&{VERIFIED_ROLE_ID}> запишитесь ещё раз."
                ),
            )

        rank = self._get_rank_from_member(interaction.user)
        await self.db.connect()
        async with self._get_lock(contract_id):
            await self.db.upsert_user(interaction.user.id, rank)
            await self.db.add_signup(contract_id, interaction.user.id)
            await self._refresh_message(interaction.message, contract)

        await self._ephemeral(interaction, "Ты записан в очередь.")

    async def handle_leave(self, interaction: Interaction):
        if not interaction.message:
            return
        if not await self._ensure_deferred(interaction):
            return
        contract_id, contract = await self._get_contract_from_message(interaction.message)
        if not contract:
            return await self._ephemeral(interaction, "Контракт не найден.")

        if contract["closed"]:
            return await self._ephemeral(interaction, "Контракт закрыт.")
        if int(contract["host_id"]) == interaction.user.id:
            return await self._ephemeral(interaction, "Хост не может выйти из записи.")

        if not isinstance(interaction.user, discord.Member):
            return await self._ephemeral(
                interaction, "Только участники сервера могут покинуть запись."
            )

        if not self._has_contract_access(interaction.user):
            return await self._ephemeral(
                interaction,
                (
                    "Вы не подтвердили свой уровень.\n"
                    f"Запись на контракт доступна только тем, кто отправил скриншот из F2 - Персонаж-Статистика в канал канал <#{CONTRACT_CHANNEL_ID}>.\n"
                    f"После того, как Вы получите роль <@&{VERIFIED_ROLE_ID}> запишитесь ещё раз."
                ),
            )

        await self.db.connect()
        async with self._get_lock(contract_id):
            await self.db.remove_signup(contract_id, interaction.user.id)
            await self._refresh_message(interaction.message, contract)

        await self._ephemeral(interaction, "Ты убран из списка.")

    async def handle_close(self, interaction: Interaction):
        if not interaction.message:
            return
        if not await self._ensure_deferred(interaction):
            return
        contract_id, contract = await self._get_contract_from_message(interaction.message)
        if not contract:
            return await self._ephemeral(interaction, "Контракт не найден.")

        if not isinstance(interaction.user, discord.Member) or not self._is_high_staff(
            interaction.user
        ):
            return await self._ephemeral(interaction, "Только High Staff может закрывать контракт.")

        if contract["closed"]:
            return await self._ephemeral(interaction, "Контракт закрыт.")

        embed = discord.Embed(
            title="Подтверждение закрытия",
            description=(
                "Вы закрываете запись!\n"
                "При подтверждении участники более не смогут покинуть запись и Вы более не сможете их исключить.\n"
                "Проверьте финальный состав перед подтверждением!"
            ),
            color=discord.Color.orange(),
        )
        view = ContractCloseConfirmView(self, contract_id, interaction.message)
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)

    async def handle_remove_user(self, interaction: Interaction):
        if not interaction.message:
            return
        if not await self._ensure_deferred(interaction):
            return
        contract_id, contract = await self._get_contract_from_message(interaction.message)
        if not contract:
            return await self._ephemeral(interaction, "Контракт не найден.")

        if not isinstance(interaction.user, discord.Member) or not self._is_high_staff(
            interaction.user
        ):
            return await self._ephemeral(interaction, "Только High Staff может убирать участников.")

        await self.db.connect()
        signups = await self.db.fetch_signups(contract_id, contract["closed"])
        if not signups:
            return await self._ephemeral(interaction, "Пока никто не записан.")

        view = RemoveUserView(self, contract_id, interaction.message, signups)
        await interaction.followup.send("Кого убрать из записи?", view=view, ephemeral=True)

    async def handle_mark_all(self, interaction: Interaction):
        if not interaction.message:
            return
        if not await self._ensure_deferred(interaction):
            return
        contract_id, contract = await self._get_contract_from_message(interaction.message)
        if not contract:
            return await self._ephemeral(interaction, "Контракт не найден.")

        if not isinstance(interaction.user, discord.Member) or not self._is_high_staff(
            interaction.user
        ):
            return await self._ephemeral(interaction, "Только High Staff может отмечать явку.")

        if not contract["closed"]:
            return await self._ephemeral(interaction, "Сначала закрой контракт.")
        if contract["attendance_marked"]:
            return await self._ephemeral(interaction, "Явка уже отмечена.")

        await self.db.connect()
        async with self._get_lock(contract_id):
            count = await self.db.mark_attendance(contract_id, interaction.user.id)
            updated = await self.db.get_contract_by_message(interaction.message.id)
            await self._refresh_message(interaction.message, updated)

        await self._ephemeral(interaction, f"Отмечено участников: {count}.")

    # ------------ Weekly reset ------------ #

    @tasks.loop(hours=1)
    async def weekly_reset_task(self):
        from datetime import timedelta

        now = datetime.now(timezone(timedelta(hours=3)))
        start = (now - timedelta(days=now.weekday())).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        async with self.db.pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute("SELECT pg_advisory_xact_lock(731824511)")
                week = await conn.fetchval(
                    "SELECT value FROM public.contract_meta WHERE key='last_weekly_reset'"
                )
                if week == start.date().isoformat():
                    return
                await conn.execute(
                    """UPDATE public.contract_users u SET weekly_attendance=(
                    SELECT COUNT(*) FROM public.attendance_events e WHERE e.user_id=u.discord_id AND e.created_at >= $1)""",
                    start,
                )
                await conn.execute(
                    """INSERT INTO public.contract_meta(key,value) VALUES('last_weekly_reset',$1)
                    ON CONFLICT(key) DO UPDATE SET value=excluded.value""",
                    start.date().isoformat(),
                )

    @weekly_reset_task.before_loop
    async def before_weekly_reset(self):
        await self.bot.wait_until_ready()
        await self.db.connect()


async def setup(bot: commands.Bot):
    cog = ContractsCog(bot)
    await bot.add_cog(cog)
    bot.add_view(ContractOpenView(cog))
    bot.add_view(AttendanceView(cog))
