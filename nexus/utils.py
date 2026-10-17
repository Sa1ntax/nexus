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
        log.info("send_log: guild=%s channel_id=%s title=%s", guild.id, channel_id, title)
        if not channel_id:
            log.warning("Log channel not set")
            return
        channel = guild.get_channel(int(channel_id))
        if channel is None:
            log.info("Channel %s not in cache, fetching...", channel_id)
            try:
                channel = await guild.fetch_channel(int(channel_id))
            except Exception as e:
                log.warning("fetch_channel failed: %s", e)
                return
        if not isinstance(channel, (discord.TextChannel, discord.Thread)):
            log.warning("Channel %s is %s, not text", channel_id, type(channel))
            return
        embed = discord.Embed(title=title, description=description[:4000], color=color, timestamp=datetime.now(timezone.utc))
        msg = await channel.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())
        log.info("Log sent to #%s (msg %s)", channel.name, msg.id)
    except Exception:
        log.exception("send_log failed")


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
