from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

import discord

from .database import get_config

log = logging.getLogger("nexus")

bot_deleted_ids: set[int] = set()
BOT_DELETED_CLEANUP_INTERVAL = 300
last_cleanup = time.monotonic()


async def send_log(guild: discord.Guild, title: str, description: str, *, color: discord.Color = discord.Color.blurple()) -> None:
    try:
        config = await get_config(guild.id)
        channel_id = config["log_channel_id"]
        if not channel_id:
            log.warning("Log channel not set for guild %s", guild.id)
            return
        channel = guild.get_channel(channel_id)
        if channel is None:
            try:
                channel = await guild.fetch_channel(channel_id)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                log.warning("Could not fetch log channel %s in guild %s", channel_id, guild.id)
                return
        if not isinstance(channel, (discord.TextChannel, discord.Thread)):
            log.warning("Log channel %s is not a text channel", channel_id)
            return
        embed = discord.Embed(title=title, description=description[:4000], color=color, timestamp=datetime.now(timezone.utc))
        await channel.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())
    except (discord.Forbidden, discord.HTTPException):
        log.exception("Could not send a moderation log for guild %s", guild.id)


def is_moderator(interaction: discord.Interaction) -> bool:
    if not isinstance(interaction.user, discord.Member):
        return False
    p = interaction.user.guild_permissions
    return p.administrator or p.moderate_members or p.kick_members or p.ban_members


def can_manage_config(interaction: discord.Interaction) -> bool:
    return isinstance(interaction.user, discord.Member) and (
        interaction.user.guild_permissions.administrator or interaction.user.guild_permissions.manage_guild
    )


async def moderator_check(interaction: discord.Interaction) -> bool:
    if not is_moderator(interaction):
        raise discord.app_commands.CheckFailure("Нужны права модератора.")
    return True


async def config_check(interaction: discord.Interaction) -> bool:
    if not can_manage_config(interaction):
        raise discord.app_commands.CheckFailure("Нужны права Manage Server или Administrator.")
    return True


async def respond(interaction: discord.Interaction, content: str, *, ephemeral: bool = True) -> None:
    try:
        if interaction.response.is_done():
            await interaction.followup.send(content, ephemeral=ephemeral)
        else:
            await interaction.response.send_message(content, ephemeral=ephemeral)
    except discord.NotFound:
        # Interaction expired (>3s) — try followup anyway
        try:
            await interaction.followup.send(content, ephemeral=ephemeral)
        except Exception:
            log.warning("Could not respond to interaction (expired)")


def mark_deleted_by_bot(message_id: int) -> None:
    global last_cleanup
    bot_deleted_ids.add(message_id)
    now = time.monotonic()
    if now - last_cleanup > BOT_DELETED_CLEANUP_INTERVAL and len(bot_deleted_ids) > 5000:
        bot_deleted_ids.clear()
        last_cleanup = now
