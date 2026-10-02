import asyncio
from functools import wraps
from weakref import WeakValueDictionary

import discord

from serenity.repositories.state import StateRepository
from serenity.ui.base import reply

_locks = WeakValueDictionary()


def channel_mutation(function):
    @wraps(function)
    async def wrapped(channel, *args, **kwargs):
        lock = _locks.setdefault(("voice", channel.id), asyncio.Lock())
        async with lock:
            return await function(channel, *args, **kwargs)

    return wrapped


def signup_mutation(function):
    @wraps(function)
    async def wrapped(self, interaction, button):
        view = getattr(self, "signup_view", self)
        lock = _locks.setdefault(("signup", view.message.id), asyncio.Lock())
        async with lock:
            data = await StateRepository().get(view.message.guild.id, "bronya", view.message.id)
            if data:
                if data.get("no_buttons"):
                    return await reply(interaction, "Эта запись окончательно закрыта.")
                view.participants = [
                    interaction.guild.get_member(uid) or discord.Object(id=uid)
                    for uid in data["participants"]
                ]
                view.closed = data["closed"]
                view.max_participants = data["max_participants"]
            return await function(self, interaction, button)

    return wrapped
