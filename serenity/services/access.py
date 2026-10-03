from discord import app_commands

from serenity.config import get_settings


def can_manage(member):
    settings = get_settings()
    return getattr(getattr(member, "guild", None), "id", None) == settings.guild_id and (
        member.guild_permissions.administrator
        or any(role.id == settings.high_staff_role_id for role in member.roles)
    )


def high_staff():
    async def predicate(interaction):
        return any(role.id == get_settings().high_staff_role_id for role in interaction.user.roles)

    return app_commands.check(predicate)


def staff():
    async def predicate(interaction):
        return any(role.id in get_settings().staff_role_ids for role in interaction.user.roles)

    return app_commands.check(predicate)
