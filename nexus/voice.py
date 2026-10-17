from __future__ import annotations

import logging
from typing import Optional

import discord

from . import database
from .database import get_config

log = logging.getLogger("nexus")

# channel_id -> owner_id
active_rooms: dict[int, int] = {}


async def ensure_voice_tables() -> None:
    assert database.db
    await database.db.execute("""
        CREATE TABLE IF NOT EXISTS voice_settings (
            guild_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            name TEXT,
            user_limit INTEGER NOT NULL DEFAULT 0,
            bitrate INTEGER NOT NULL DEFAULT 64000,
            locked INTEGER NOT NULL DEFAULT 1,
            PRIMARY KEY (guild_id, user_id)
        )
    """)
    await database.db.execute("""
        CREATE TABLE IF NOT EXISTS voice_whitelist (
            guild_id INTEGER NOT NULL,
            owner_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            PRIMARY KEY (guild_id, owner_id, user_id)
        )
    """)
    await database.db.execute("""
        CREATE TABLE IF NOT EXISTS voice_config (
            guild_id INTEGER PRIMARY KEY,
            hub_channel_id INTEGER,
            category_id INTEGER
        )
    """)


async def get_voice_config(guild_id: int) -> dict:
    assert database.db
    cur = await database.db.execute(
        "SELECT hub_channel_id, category_id FROM voice_config WHERE guild_id=?", (guild_id,)
    )
    row = await cur.fetchone()
    if not row:
        return {"hub_channel_id": None, "category_id": None}
    return {"hub_channel_id": int(row[0]) if row[0] else None, "category_id": int(row[1]) if row[1] else None}


async def get_user_voice_settings(guild_id: int, user_id: int) -> dict:
    assert database.db
    cur = await database.db.execute(
        "SELECT name, user_limit, bitrate, locked FROM voice_settings WHERE guild_id=? AND user_id=?",
        (guild_id, user_id),
    )
    row = await cur.fetchone()
    if not row:
        return {"name": None, "user_limit": 0, "bitrate": 64000, "locked": True}
    return {
        "name": row[0],
        "user_limit": int(row[1] or 0),
        "bitrate": int(row[2] or 64000),
        "locked": bool(row[3]),
    }


async def save_user_voice_settings(guild_id: int, user_id: int, **kwargs) -> None:
    assert database.db
    cur = await get_user_voice_settings(guild_id, user_id)
    cur.update(kwargs)
    await database.db.execute(
        """INSERT OR REPLACE INTO voice_settings (guild_id, user_id, name, user_limit, bitrate, locked)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (guild_id, user_id, cur["name"], cur["user_limit"], cur["bitrate"], int(cur["locked"])),
    )


async def get_whitelist(guild_id: int, owner_id: int) -> set[int]:
    assert database.db
    cur = await database.db.execute(
        "SELECT user_id FROM voice_whitelist WHERE guild_id=? AND owner_id=?", (guild_id, owner_id)
    )
    return {int(r[0]) for r in await cur.fetchall()}


async def add_whitelist(guild_id: int, owner_id: int, user_id: int) -> None:
    assert database.db
    await database.db.execute(
        "INSERT OR IGNORE INTO voice_whitelist (guild_id, owner_id, user_id) VALUES (?, ?, ?)",
        (guild_id, owner_id, user_id),
    )


async def remove_whitelist(guild_id: int, owner_id: int, user_id: int) -> None:
    assert database.db
    await database.db.execute(
        "DELETE FROM voice_whitelist WHERE guild_id=? AND owner_id=? AND user_id=?",
        (guild_id, owner_id, user_id),
    )



class RoomEntry(discord.ui.View):
    def __init__(self, owner_id: int, channel_id: int):
        super().__init__(timeout=None)
        self.owner_id = owner_id
        self.channel_id = channel_id

    @discord.ui.button(label="Управление комнатой", style=discord.ButtonStyle.primary, custom_id="vc_open")
    async def open_panel(self, i: discord.Interaction, b: discord.ui.Button):
        if i.user.id != self.owner_id:
            await i.response.send_message("Управление доступно только создателю комнаты.", ephemeral=True)
            return
        view = RoomControl(self.owner_id, self.channel_id)
        await i.response.send_message(embed=view.embed(), view=view, ephemeral=True)


class RoomControl(discord.ui.View):
    def __init__(self, owner_id: int, channel_id: int):
        super().__init__(timeout=300)
        self.owner_id = owner_id
        self.channel_id = channel_id
        self.add_item(RoomSelect(owner_id, channel_id))

    def embed(self) -> discord.Embed:
        return discord.Embed(
            title="Комната",
            description="Выбери действие.",
            color=0x2B2D31,
        )


class RoomSelect(discord.ui.Select):
    def __init__(self, owner_id: int, channel_id: int):
        self.owner_id = owner_id
        self.channel_id = channel_id
        options = [
            discord.SelectOption(label="Название", value="rename", description="Переименовать комнату"),
            discord.SelectOption(label="Лимит", value="limit", description="Максимум участников"),
            discord.SelectOption(label="Битрейт", value="bitrate", description="Качество звука"),
            discord.SelectOption(label="Регион", value="region", description="Голосовой регион"),
            discord.SelectOption(label="Закрыть", value="lock", description="Только по приглашению"),
            discord.SelectOption(label="Открыть", value="unlock", description="Могут заходить все"),
            discord.SelectOption(label="Скрыть", value="hide", description="Скрыть из списка каналов"),
            discord.SelectOption(label="Показать", value="unhide", description="Снова показать канал"),
            discord.SelectOption(label="Пустить", value="allow", description="Добавить в белый список"),
            discord.SelectOption(label="Выгнать", value="kick", description="Убрать из комнаты"),
            discord.SelectOption(label="Удалить", value="delete", description="Удалить комнату"),
        ]
        super().__init__(placeholder="Действие…", options=options)

    async def _ch(self, i: discord.Interaction):
        ch = i.guild.get_channel(self.channel_id)
        return ch if isinstance(ch, discord.VoiceChannel) else None

    async def callback(self, i: discord.Interaction):
        v = self.values[0]
        ch = await self._ch(i)
        if v == "rename":
            await i.response.send_modal(RenameModal(self.channel_id, self.owner_id))
            return
        if v == "limit":
            await i.response.send_modal(LimitModal(self.channel_id, self.owner_id))
            return
        if v == "bitrate":
            await i.response.send_modal(BitrateModal(self.channel_id, self.owner_id))
            return
        if v == "region":
            await i.response.send_message("Регион:", view=RegionView(self.channel_id, self.owner_id), ephemeral=True)
            return
        if v == "allow":
            await i.response.send_message("Кого пустить:", view=WhitelistAddView(self.owner_id, self.channel_id), ephemeral=True)
            return
        if v == "kick":
            await i.response.send_message("Кого выгнать:", view=KickFromRoomView(self.owner_id, self.channel_id), ephemeral=True)
            return
        if not ch:
            await i.response.send_message("Канал не найден.", ephemeral=True)
            return
        if v == "lock":
            await save_user_voice_settings(i.guild.id, self.owner_id, locked=True)
            await apply_permissions(ch, i.guild.get_member(self.owner_id), True)
            await i.response.send_message("Комната закрыта.", ephemeral=True)
        elif v == "unlock":
            await save_user_voice_settings(i.guild.id, self.owner_id, locked=False)
            await apply_permissions(ch, i.guild.get_member(self.owner_id), False)
            await i.response.send_message("Комната открыта.", ephemeral=True)
        elif v == "hide":
            ow = ch.overwrites_for(i.guild.default_role)
            ow.view_channel = False
            await ch.set_permissions(i.guild.default_role, overwrite=ow)
            await i.response.send_message("Комната скрыта.", ephemeral=True)
        elif v == "unhide":
            ow = ch.overwrites_for(i.guild.default_role)
            ow.view_channel = True
            await ch.set_permissions(i.guild.default_role, overwrite=ow)
            await i.response.send_message("Комната видна.", ephemeral=True)
        elif v == "delete":
            await ch.delete(reason="Владелец удалил комнату")
            active_rooms.pop(self.channel_id, None)
            await i.response.send_message("Комната удалена.", ephemeral=True)


class RenameModal(discord.ui.Modal, title="Название комнаты"):
    name = discord.ui.TextInput(label="Название", max_length=100)

    def __init__(self, channel_id: int, owner_id: int):
        super().__init__()
        self.channel_id = channel_id
        self.owner_id = owner_id

    async def on_submit(self, i: discord.Interaction):
        ch = i.guild.get_channel(self.channel_id)
        if isinstance(ch, discord.VoiceChannel):
            await ch.edit(name=self.name.value[:100])
            await save_user_voice_settings(i.guild.id, self.owner_id, name=self.name.value[:100])
            await i.response.send_message("Название обновлено.", ephemeral=True)
        else:
            await i.response.send_message("Канал не найден.", ephemeral=True)


class LimitModal(discord.ui.Modal, title="Лимит участников"):
    limit = discord.ui.TextInput(label="0–99 (0 = без лимита)", placeholder="0")

    def __init__(self, channel_id: int, owner_id: int):
        super().__init__()
        self.channel_id = channel_id
        self.owner_id = owner_id

    async def on_submit(self, i: discord.Interaction):
        if not self.limit.value.isdigit():
            await i.response.send_message("Нужно число.", ephemeral=True)
            return
        n = max(0, min(int(self.limit.value), 99))
        ch = i.guild.get_channel(self.channel_id)
        if isinstance(ch, discord.VoiceChannel):
            await ch.edit(user_limit=n)
            await save_user_voice_settings(i.guild.id, self.owner_id, user_limit=n)
            await i.response.send_message(f"Лимит: {n or 'нет'}.", ephemeral=True)
        else:
            await i.response.send_message("Канал не найден.", ephemeral=True)


class WhitelistAddView(discord.ui.View):
    def __init__(self, owner_id: int, channel_id: int):
        super().__init__(timeout=60)
        self.owner_id = owner_id
        self.channel_id = channel_id
        self.add_item(WhitelistUserSelect(owner_id, channel_id))


class WhitelistUserSelect(discord.ui.UserSelect):
    def __init__(self, owner_id: int, channel_id: int):
        super().__init__(placeholder="Кого пустить…")
        self.owner_id = owner_id
        self.channel_id = channel_id

    async def callback(self, i: discord.Interaction):
        user = self.values[0]
        await add_whitelist(i.guild.id, self.owner_id, user.id)
        ch = i.guild.get_channel(self.channel_id)
        if isinstance(ch, discord.VoiceChannel):
            await ch.set_permissions(user, connect=True, view_channel=True)
        await i.response.send_message(f"{user.mention} добавлен в белый список.", ephemeral=True)


async def apply_permissions(channel: discord.VoiceChannel, owner: Optional[discord.Member], locked: bool) -> None:
    if not owner:
        return
    overwrites = {
        owner.guild.default_role: discord.PermissionOverwrite(connect=not locked, view_channel=True),
        owner: discord.PermissionOverwrite(connect=True, manage_channels=True, move_members=True, view_channel=True),
        owner.guild.me: discord.PermissionOverwrite(connect=True, manage_channels=True, move_members=True, view_channel=True),
    }
    wl = await get_whitelist(owner.guild.id, owner.id)
    for uid in wl:
        member = owner.guild.get_member(uid)
        if member:
            overwrites[member] = discord.PermissionOverwrite(connect=True, view_channel=True)
    await channel.edit(overwrites=overwrites)


async def create_room(member: discord.Member, hub: discord.VoiceChannel) -> Optional[discord.VoiceChannel]:
    settings = await get_user_voice_settings(member.guild.id, member.id)
    name = settings["name"] or f"Комната {member.display_name}"
    cfg = await get_voice_config(member.guild.id)
    category = member.guild.get_channel(cfg["category_id"]) if cfg["category_id"] else hub.category
    channel = await member.guild.create_voice_channel(
        name=name[:100],
        category=category if isinstance(category, discord.CategoryChannel) else None,
        user_limit=settings["user_limit"],
        bitrate=min(settings["bitrate"], member.guild.bitrate_limit),
        reason="Nexus private room",
    )
    await apply_permissions(channel, member, settings["locked"])
    active_rooms[channel.id] = member.id
    try:
        await member.move_to(channel)
    except discord.HTTPException:
        log.warning("Could not move %s to new room", member.id)
    try:
        await channel.send(
            f"{member.mention}",
            view=RoomEntry(member.id, channel.id),
        )
    except discord.HTTPException:
        log.warning("Could not send room entry to channel %s", channel.id)
    return channel


def setup(bot: discord.Client):
    @bot.event
    async def on_voice_state_update(member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        if member.bot:
            return
        cfg = await get_voice_config(member.guild.id)
        hub_id = cfg["hub_channel_id"]

        # joined hub -> create room
        if after.channel and hub_id and after.channel.id == hub_id:
            if before.channel and before.channel.id == hub_id:
                return
            try:
                await create_room(member, after.channel)
            except discord.Forbidden:
                log.warning("No permission to create voice channel in %s", member.guild.id)
            except Exception:
                log.exception("create_room failed")

        # left a managed room and it's empty -> delete
        if before.channel and before.channel.id in active_rooms:
            ch = before.channel
            if len(ch.members) == 0:
                try:
                    await ch.delete(reason="Комната пуста")
                except discord.HTTPException:
                    pass
                active_rooms.pop(ch.id, None)
