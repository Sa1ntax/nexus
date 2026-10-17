from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from typing import Optional

import discord
from discord import app_commands

from . import database
from .database import count_warnings, get_config
from .utils import moderator_check, respond, send_log

pending_tempbans: dict[tuple[int, int], float] = {}


async def apply_escalation(guild: discord.Guild, member: discord.Member, count: int):
    cfg = await get_config(guild.id)
    reason = f"Эскалация варнов ({count})"
    if cfg["warn_ban_threshold"] and count >= cfg["warn_ban_threshold"]:
        try:
            await member.ban(reason=reason)
            await send_log(guild, "Эскалация: бан", f"{member} забанен после {count} варнов", color=discord.Color.red())
            return
        except discord.Forbidden:
            pass
    if cfg["warn_kick_threshold"] and count >= cfg["warn_kick_threshold"]:
        try:
            await member.kick(reason=reason)
            await send_log(guild, "Эскалация: кик", f"{member} кикнут после {count} варнов", color=discord.Color.red())
            return
        except discord.Forbidden:
            pass
    if cfg["warn_timeout_threshold"] and count >= cfg["warn_timeout_threshold"]:
        try:
            await member.timeout(timedelta(minutes=cfg["warn_timeout_minutes"]), reason=reason)
            await send_log(guild, "Эскалация: timeout", f"{member.mention} получил {cfg['warn_timeout_minutes']} мин после {count} варнов", color=discord.Color.orange())
        except discord.Forbidden:
            pass


def setup(bot):
    @bot.tree.command(name="warn")
    @app_commands.check(moderator_check)
    async def warn(interaction: discord.Interaction, member: discord.Member, reason: str):
        assert interaction.guild and database.db
        if member.bot or member.id == interaction.user.id:
            await respond(interaction, "Нельзя.")
            return
        await database.db.execute(
            "INSERT INTO warnings (guild_id, user_id, moderator_id, reason, created_at) VALUES (?, ?, ?, ?, ?)",
            (interaction.guild.id, member.id, interaction.user.id, reason[:1000], datetime.now(timezone.utc).isoformat()),
        )
        await database.db.commit()
        count = await count_warnings(interaction.guild.id, member.id)
        await respond(interaction, f"Варн выдан {member.mention} (всего {count}). Причина: {reason}")
        await send_log(interaction.guild, "Варн", f"{member.mention} от {interaction.user.mention}\n{reason} (всего {count})", color=discord.Color.orange())
        await apply_escalation(interaction.guild, member, count)

    @bot.tree.command(name="warnings")
    @app_commands.check(moderator_check)
    async def warnings_cmd(interaction: discord.Interaction, member: discord.Member):
        assert interaction.guild and database.db
        cur = await database.db.execute(
            "SELECT moderator_id, reason, created_at FROM warnings WHERE guild_id=? AND user_id=? ORDER BY id DESC LIMIT 15",
            (interaction.guild.id, member.id),
        )
        rows = await cur.fetchall()
        if not rows:
            await respond(interaction, f"У {member.mention} нет варнов.")
            return
        lines = [f"• `{r[2][:16].replace('T',' ')}` <@{r[0]}>: {r[1]}" for r in rows]
        embed = discord.Embed(title=f"Варны: {member}", description="\n".join(lines)[:4000], color=discord.Color.orange())
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @bot.tree.command(name="clear_warnings")
    @app_commands.check(moderator_check)
    async def clear_warnings(interaction: discord.Interaction, member: discord.Member):
        assert interaction.guild and database.db
        cur = await database.db.execute("SELECT COUNT(*) FROM warnings WHERE guild_id=? AND user_id=?", (interaction.guild.id, member.id))
        count = (await cur.fetchone())[0]
        if not count:
            await respond(interaction, "Нет варнов.")
            return
        await database.db.execute("DELETE FROM warnings WHERE guild_id=? AND user_id=?", (interaction.guild.id, member.id))
        await database.db.commit()
        await respond(interaction, f"Очищено {count} варнов у {member.mention}.")
        await send_log(interaction.guild, "Варны очищены", f"{member.mention} модератором {interaction.user.mention} ({count})")

    @bot.tree.command(name="timeout")
    @app_commands.check(moderator_check)
    async def timeout_cmd(interaction: discord.Interaction, member: discord.Member, minutes: app_commands.Range[int, 1, 40320], reason: str):
        assert interaction.guild
        if member.id == interaction.user.id:
            await respond(interaction, "Нельзя.")
            return
        try:
            await member.timeout(timedelta(minutes=minutes), reason=f"{interaction.user}: {reason}"[:512])
            await respond(interaction, f"{member.mention} — timeout {minutes} мин. {reason}")
            await send_log(interaction.guild, "Timeout", f"{member.mention} от {interaction.user.mention}\n{minutes} мин — {reason}", color=discord.Color.red())
        except discord.Forbidden:
            await respond(interaction, "Нет прав / иерархия.")

    @bot.tree.command(name="untimeout")
    @app_commands.check(moderator_check)
    async def untimeout(interaction: discord.Interaction, member: discord.Member, reason: str = "Не указана"):
        assert interaction.guild
        try:
            await member.timeout(None, reason=f"{interaction.user}: {reason}"[:512])
            await respond(interaction, f"Timeout снят с {member.mention}.")
            await send_log(interaction.guild, "Timeout снят", f"{member.mention} от {interaction.user.mention}")
        except discord.Forbidden:
            await respond(interaction, "Нет прав.")

    @bot.tree.command(name="kick")
    @app_commands.check(moderator_check)
    async def kick(interaction: discord.Interaction, member: discord.Member, reason: str):
        assert interaction.guild
        try:
            await member.kick(reason=f"{interaction.user}: {reason}"[:512])
            await respond(interaction, f"{member} кикнут. {reason}")
            await send_log(interaction.guild, "Кик", f"{member} (`{member.id}`) от {interaction.user.mention}\n{reason}", color=discord.Color.red())
        except discord.Forbidden:
            await respond(interaction, "Нет прав.")

    @bot.tree.command(name="ban")
    @app_commands.check(moderator_check)
    async def ban(interaction: discord.Interaction, member: discord.Member, reason: str, delete_message_days: app_commands.Range[int, 0, 7] = 0):
        assert interaction.guild
        if member.id == interaction.user.id:
            await respond(interaction, "Нельзя.")
            return
        try:
            await member.ban(reason=f"{interaction.user}: {reason}"[:512], delete_message_seconds=delete_message_days * 86400)
            await respond(interaction, f"{member} забанен. {reason}")
            await send_log(interaction.guild, "Бан", f"{member} (`{member.id}`) от {interaction.user.mention}\n{reason}", color=discord.Color.red())
        except discord.Forbidden:
            await respond(interaction, "Нет прав.")

    @bot.tree.command(name="tempban")
    @app_commands.describe(hours="Часы бана (1–720)")
    @app_commands.check(moderator_check)
    async def tempban(interaction: discord.Interaction, member: discord.Member, hours: app_commands.Range[int, 1, 720], reason: str):
        assert interaction.guild
        if member.id == interaction.user.id:
            await respond(interaction, "Нельзя.")
            return
        try:
            await member.ban(reason=f"{interaction.user}: tempban {hours}h — {reason}"[:512])
            pending_tempbans[(interaction.guild.id, member.id)] = time.time() + hours * 3600
            await respond(interaction, f"{member} временно забанен на {hours} ч. {reason}")
            await send_log(interaction.guild, "Временный бан", f"{member} на {hours} ч от {interaction.user.mention}\n{reason}", color=discord.Color.red())
        except discord.Forbidden:
            await respond(interaction, "Нет прав.")

    @bot.tree.command(name="unban")
    @app_commands.check(moderator_check)
    async def unban(interaction: discord.Interaction, user_id: str, reason: str = "Не указана"):
        assert interaction.guild
        if not user_id.isdigit():
            await respond(interaction, "ID только цифры.")
            return
        try:
            user = await bot.fetch_user(int(user_id))
            await interaction.guild.unban(user, reason=f"{interaction.user}: {reason}"[:512])
            pending_tempbans.pop((interaction.guild.id, user.id), None)
            await respond(interaction, f"Разбанен {user}.")
            await send_log(interaction.guild, "Разбан", f"{user} от {interaction.user.mention}")
        except discord.NotFound:
            await respond(interaction, "Не найден в банах.")
        except discord.Forbidden:
            await respond(interaction, "Нет прав.")

    @bot.tree.command(name="purge")
    @app_commands.check(moderator_check)
    async def purge(interaction: discord.Interaction, amount: app_commands.Range[int, 1, 100]):
        if not isinstance(interaction.channel, discord.TextChannel):
            await respond(interaction, "Только текстовые каналы.")
            return
        if not interaction.channel.permissions_for(interaction.guild.me).manage_messages:
            await respond(interaction, "Нужно Manage Messages.")
            return
        await interaction.response.defer(ephemeral=True)
        cutoff = datetime.now(timezone.utc) - timedelta(days=14)
        deleted = await interaction.channel.purge(limit=amount, check=lambda m: m.created_at > cutoff)
        await interaction.followup.send(f"Удалено: {len(deleted)} (старше 14 дней пропущены).", ephemeral=True)
        if interaction.guild:
            await send_log(interaction.guild, "Purge", f"{interaction.user.mention} в {interaction.channel.mention}: {len(deleted)}")

    @bot.tree.command(name="lock")
    @app_commands.check(moderator_check)
    async def lock(interaction: discord.Interaction, channel: Optional[discord.TextChannel] = None, reason: str = "Локдаун"):
        ch = channel or interaction.channel
        if not isinstance(ch, discord.TextChannel):
            await respond(interaction, "Только текстовый канал.")
            return
        try:
            overwrite = ch.overwrites_for(interaction.guild.default_role)
            overwrite.send_messages = False
            await ch.set_permissions(interaction.guild.default_role, overwrite=overwrite, reason=f"{interaction.user}: {reason}")
            await respond(interaction, f"Канал {ch.mention} залочен.")
            await send_log(interaction.guild, "Lock", f"{ch.mention} от {interaction.user.mention}\n{reason}")
        except discord.Forbidden:
            await respond(interaction, "Нет прав Manage Channels.")

    @bot.tree.command(name="unlock")
    @app_commands.check(moderator_check)
    async def unlock(interaction: discord.Interaction, channel: Optional[discord.TextChannel] = None):
        ch = channel or interaction.channel
        if not isinstance(ch, discord.TextChannel):
            await respond(interaction, "Только текстовый канал.")
            return
        try:
            overwrite = ch.overwrites_for(interaction.guild.default_role)
            overwrite.send_messages = None
            await ch.set_permissions(interaction.guild.default_role, overwrite=overwrite, reason=f"{interaction.user}: unlock")
            await respond(interaction, f"Канал {ch.mention} разлочен.")
            await send_log(interaction.guild, "Unlock", f"{ch.mention} от {interaction.user.mention}")
        except discord.Forbidden:
            await respond(interaction, "Нет прав.")

    @bot.tree.command(name="slowmode")
    @app_commands.describe(seconds="0–21600 (0 = выкл)")
    @app_commands.check(moderator_check)
    async def slowmode(interaction: discord.Interaction, seconds: app_commands.Range[int, 0, 21600], channel: Optional[discord.TextChannel] = None):
        ch = channel or interaction.channel
        if not isinstance(ch, discord.TextChannel):
            await respond(interaction, "Только текстовый канал.")
            return
        try:
            await ch.edit(slowmode_delay=seconds, reason=f"{interaction.user}: slowmode")
            await respond(interaction, f"Slowmode в {ch.mention}: {seconds} сек.")
            await send_log(interaction.guild, "Slowmode", f"{ch.mention} → {seconds}s от {interaction.user.mention}")
        except discord.Forbidden:
            await respond(interaction, "Нет прав.")
