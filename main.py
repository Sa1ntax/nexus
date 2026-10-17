from __future__ import annotations

import asyncio
import logging
import os
import time

import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

from nexus.automod import setup as setup_automod
from nexus.panel import setup as setup_panel
from nexus.config_commands import setup as setup_config
from nexus.database import db, init_db
from nexus.moderation import pending_tempbans, setup as setup_moderation
from nexus.urlhaus import URLHAUS_AUTH_KEY, update_urlhaus
from nexus.utils import respond
from nexus.verification import VerifyView

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
GUILD_ID_RAW = os.getenv("GUILD_ID", "").strip()
GUILD_ID = int(GUILD_ID_RAW) if GUILD_ID_RAW.isdigit() else None

if not TOKEN:
    raise RuntimeError("DISCORD_TOKEN is missing.")

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")
log = logging.getLogger("nexus")

intents = discord.Intents.default()
intents.guilds = True
intents.members = True
intents.message_content = True

bot = commands.Bot(command_prefix=commands.when_mentioned, intents=intents)


async def urlhaus_loop():
    await bot.wait_until_ready()
    await update_urlhaus()
    while not bot.is_closed():
        await asyncio.sleep(600)
        await update_urlhaus()


async def tempban_loop():
    await bot.wait_until_ready()
    while not bot.is_closed():
        now = time.time()
        to_remove = []
        for key, ts in list(pending_tempbans.items()):
            if now >= ts:
                guild_id, user_id = key
                guild = bot.get_guild(guild_id)
                if guild:
                    try:
                        user = await bot.fetch_user(user_id)
                        await guild.unban(user, reason="Nexus: истёк временный бан")
                        from nexus.utils import send_log
                        await send_log(guild, "Временный бан истёк", f"Пользователь {user} (`{user_id}`) разбанен автоматически.")
                    except Exception:
                        log.exception("Tempban unban failed")
                to_remove.append(key)
        for k in to_remove:
            pending_tempbans.pop(k, None)
        await asyncio.sleep(30)


@bot.event
async def on_ready():
    log.info("Logged in as %s", bot.user)
    bot.add_view(VerifyView())
    if not getattr(bot, "_synced", False):
        try:
            if GUILD_ID:
                g = discord.Object(id=GUILD_ID)
                bot.tree.clear_commands(guild=None)
                await bot.tree.sync()
                bot.tree.copy_global_to(guild=g)
                synced = await bot.tree.sync(guild=g)
                log.info("Synced %s commands to guild %s", len(synced), GUILD_ID)
            else:
                synced = await bot.tree.sync()
                log.info("Synced %s global commands", len(synced))
            bot._synced = True
        except Exception:
            log.exception("Sync failed")
    bot.loop.create_task(tempban_loop())
    if URLHAUS_AUTH_KEY:
        bot.loop.create_task(urlhaus_loop())
    else:
        log.warning("URLHAUS_AUTH_KEY not set — URLhaus disabled")


@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    msg = str(error) if isinstance(error, app_commands.CheckFailure) else "Ошибка команды. Смотри логи."
    if not isinstance(error, app_commands.CheckFailure):
        log.exception("Command error", exc_info=error)
    try:
        await respond(interaction, msg)
    except discord.HTTPException:
        pass


async def main():
    await init_db()
    setup_config(bot)
    setup_moderation(bot)
    setup_automod(bot)
    setup_panel(bot)
    try:
        await bot.start(TOKEN)
    finally:
        if db is not None:
            await db.close()


if __name__ == "__main__":
    asyncio.run(main())
