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
    pass  # commands moved to /panel
