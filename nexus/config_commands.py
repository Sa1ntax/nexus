from __future__ import annotations

import logging

from typing import Optional

import discord
from discord import app_commands

from . import database
from .database import ensure_guild_config, get_allowed_domains, get_banned_words, get_config, get_ignored_channels, get_whitelist_roles
from .urlhaus import URLHAUS_AUTH_KEY
log = logging.getLogger("nexus")

from .utils import config_check, respond


class ConfigGroup(app_commands.Group):
    def __init__(self):
        super().__init__(name="config", description="Настройки Nexus")

    @app_commands.command(name="show", description="Показать настройки")
    @app_commands.check(config_check)
    async def show(self, interaction: discord.Interaction):
        assert interaction.guild
        cfg = await get_config(interaction.guild.id)
        domains = sorted(await get_allowed_domains(interaction.guild.id))
        ignored = await get_ignored_channels(interaction.guild.id)
        wl_roles = await get_whitelist_roles(interaction.guild.id)
        words = sorted(await get_banned_words(interaction.guild.id))
        if cfg["log_channel_id"]:
            ch = interaction.guild.get_channel(cfg["log_channel_id"])
            channel = f"{ch.mention} (`{cfg['log_channel_id']}`)" if ch else f"ID `{cfg['log_channel_id']}` (бот не видит канал)"
        else:
            channel = "не задан"
        vrole = f"<@&{cfg['verify_role_id']}>" if cfg["verify_role_id"] else "не задана"
        vchan = f"<#{cfg['verify_channel_id']}>" if cfg["verify_channel_id"] else "не задан"
        uh = "вкл" if cfg.get("urlhaus_enabled") else "выкл"
        if not URLHAUS_AUTH_KEY:
            uh += " (ключ не задан)"
        embed = discord.Embed(title="Nexus — настройки", color=discord.Color.blurple())
        embed.add_field(name="Канал логов", value=channel, inline=False)
        embed.add_field(name="Фильтр ссылок", value="вкл" if cfg["link_filter_enabled"] else "выкл")
        embed.add_field(name="URLhaus", value=uh)
        embed.add_field(name="Уведомление ссылок", value="да" if cfg["link_notice_enabled"] else "нет")
        embed.add_field(name="Антифлуд", value="вкл" if cfg["antispam_enabled"] else "выкл")
        embed.add_field(name="Таймаут антифлуда", value=f"{cfg['spam_timeout_minutes']} мин")
        embed.add_field(name="Спам упоминаниями", value="вкл" if cfg["mention_spam_enabled"] else "выкл")
        embed.add_field(name="Фильтр слов", value="вкл" if cfg["word_filter_enabled"] else "выкл")
        embed.add_field(name="Мин. возраст", value=f"{cfg['min_account_age_days']} дн")
        embed.add_field(name="Верификация", value="вкл" if cfg["verify_enabled"] else "выкл")
        embed.add_field(name="Роль верификации", value=vrole)
        embed.add_field(name="Канал верификации", value=vchan)
        embed.add_field(name="Эскалация: timeout", value=f"после {cfg['warn_timeout_threshold']} варнов на {cfg['warn_timeout_minutes']} мин" if cfg["warn_timeout_threshold"] else "выкл")
        embed.add_field(name="Эскалация: kick", value=f"после {cfg['warn_kick_threshold']}" if cfg["warn_kick_threshold"] else "выкл")
        embed.add_field(name="Эскалация: ban", value=f"после {cfg['warn_ban_threshold']}" if cfg["warn_ban_threshold"] else "выкл")
        embed.add_field(name="Разрешённые домены", value=", ".join(domains) or "нет", inline=False)
        embed.add_field(name="Игнор-каналы", value=", ".join(f"<#{c}>" for c in ignored) or "нет", inline=False)
        embed.add_field(name="Whitelist роли", value=", ".join(f"<@&{r}>" for r in wl_roles) or "нет", inline=False)
        embed.add_field(name="Запрещённые слова", value=", ".join(words) or "нет", inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="log_channel")
    @app_commands.check(config_check)
    async def log_channel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        assert interaction.guild and database.db
        await interaction.response.defer(ephemeral=True)
        await ensure_guild_config(interaction.guild.id)
        log.info("Saving log channel: id=%s name=%s guild=%s", channel.id, channel.name, interaction.guild.id)
        await database.db.execute("UPDATE guild_config SET log_channel_id = ? WHERE guild_id = ?", (int(channel.id), interaction.guild.id))
        await database.db.commit()
        # verify
        cur = await database.db.execute("SELECT log_channel_id FROM guild_config WHERE guild_id = ?", (interaction.guild.id,))
        row = await cur.fetchone()
        saved = row[0] if row else None
        log.info("Saved log_channel_id=%s (type=%s)", saved, type(saved))
        await interaction.followup.send(f"Канал логов: {channel.mention} (ID `{channel.id}`, в базе `{saved}`)", ephemeral=True)

    @app_commands.command(name="links")
    @app_commands.check(config_check)
    async def links(self, interaction: discord.Interaction, enabled: bool):
        assert interaction.guild and database.db
        await ensure_guild_config(interaction.guild.id)
        await database.db.execute("UPDATE guild_config SET link_filter_enabled = ? WHERE guild_id = ?", (int(enabled), interaction.guild.id))
        await database.db.commit()
        await respond(interaction, f"Фильтр ссылок {'вкл' if enabled else 'выкл'}.")

    @app_commands.command(name="link_notice")
    @app_commands.check(config_check)
    async def link_notice(self, interaction: discord.Interaction, enabled: bool):
        assert interaction.guild and database.db
        await ensure_guild_config(interaction.guild.id)
        await database.db.execute("UPDATE guild_config SET link_notice_enabled = ? WHERE guild_id = ?", (int(enabled), interaction.guild.id))
        await database.db.commit()
        await respond(interaction, f"Уведомление ссылок {'вкл' if enabled else 'выкл'}.")

    @app_commands.command(name="antispam")
    @app_commands.check(config_check)
    async def antispam(self, interaction: discord.Interaction, enabled: bool):
        assert interaction.guild and database.db
        await ensure_guild_config(interaction.guild.id)
        await database.db.execute("UPDATE guild_config SET antispam_enabled = ? WHERE guild_id = ?", (int(enabled), interaction.guild.id))
        await database.db.commit()
        await respond(interaction, f"Антифлуд {'вкл' if enabled else 'выкл'}.")

    @app_commands.command(name="spam_timeout")
    @app_commands.check(config_check)
    async def spam_timeout(self, interaction: discord.Interaction, minutes: app_commands.Range[int, 1, 60]):
        assert interaction.guild and database.db
        await ensure_guild_config(interaction.guild.id)
        await database.db.execute("UPDATE guild_config SET spam_timeout_minutes = ? WHERE guild_id = ?", (minutes, interaction.guild.id))
        await database.db.commit()
        await respond(interaction, f"Таймаут антифлуда: {minutes} мин.")

    @app_commands.command(name="min_age")
    @app_commands.check(config_check)
    async def min_age(self, interaction: discord.Interaction, days: app_commands.Range[int, 0, 365]):
        assert interaction.guild and database.db
        await ensure_guild_config(interaction.guild.id)
        await database.db.execute("UPDATE guild_config SET min_account_age_days = ? WHERE guild_id = ?", (days, interaction.guild.id))
        await database.db.commit()
        await respond(interaction, f"Мин. возраст: {days} дн.")

    @app_commands.command(name="word_filter")
    @app_commands.check(config_check)
    async def word_filter(self, interaction: discord.Interaction, enabled: bool):
        assert interaction.guild and database.db
        await ensure_guild_config(interaction.guild.id)
        await database.db.execute("UPDATE guild_config SET word_filter_enabled = ? WHERE guild_id = ?", (int(enabled), interaction.guild.id))
        await database.db.commit()
        await respond(interaction, f"Фильтр слов {'вкл' if enabled else 'выкл'}.")

    @app_commands.command(name="mention_spam")
    @app_commands.check(config_check)
    async def mention_spam(self, interaction: discord.Interaction, enabled: bool):
        assert interaction.guild and database.db
        await ensure_guild_config(interaction.guild.id)
        await database.db.execute("UPDATE guild_config SET mention_spam_enabled = ? WHERE guild_id = ?", (int(enabled), interaction.guild.id))
        await database.db.commit()
        await respond(interaction, f"Антиспам упоминаний {'вкл' if enabled else 'выкл'}.")

    @app_commands.command(name="allow_domain")
    @app_commands.check(config_check)
    async def allow_domain(self, interaction: discord.Interaction, domain: str):
        assert interaction.guild and database.db
        domain = domain.strip().lower().rstrip(".")
        if "://" in domain or "/" in domain or " " in domain or "." not in domain:
            await respond(interaction, "Укажи только домен.")
            return
        await database.db.execute("INSERT OR IGNORE INTO allowed_domains (guild_id, domain) VALUES (?, ?)", (interaction.guild.id, domain))
        await database.db.commit()
        await respond(interaction, f"Домен `{domain}` разрешён.")

    @app_commands.command(name="remove_domain")
    @app_commands.check(config_check)
    async def remove_domain(self, interaction: discord.Interaction, domain: str):
        assert interaction.guild and database.db
        domain = domain.strip().lower().rstrip(".")
        await database.db.execute("DELETE FROM allowed_domains WHERE guild_id = ? AND domain = ?", (interaction.guild.id, domain))
        await database.db.commit()
        await respond(interaction, f"Домен `{domain}` удалён.")

    @app_commands.command(name="ignore_channel")
    @app_commands.check(config_check)
    async def ignore_channel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        assert interaction.guild and database.db
        await database.db.execute("INSERT OR IGNORE INTO ignored_channels (guild_id, channel_id) VALUES (?, ?)", (interaction.guild.id, channel.id))
        await database.db.commit()
        await respond(interaction, f"{channel.mention} в игноре.")

    @app_commands.command(name="unignore_channel")
    @app_commands.check(config_check)
    async def unignore_channel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        assert interaction.guild and database.db
        await database.db.execute("DELETE FROM ignored_channels WHERE guild_id = ? AND channel_id = ?", (interaction.guild.id, channel.id))
        await database.db.commit()
        await respond(interaction, f"{channel.mention} убран из игнора.")

    @app_commands.command(name="whitelist_role")
    @app_commands.check(config_check)
    async def whitelist_role(self, interaction: discord.Interaction, role: discord.Role):
        assert interaction.guild and database.db
        await database.db.execute("INSERT OR IGNORE INTO whitelist_roles (guild_id, role_id) VALUES (?, ?)", (interaction.guild.id, role.id))
        await database.db.commit()
        await respond(interaction, f"Роль {role.mention} в whitelist.")

    @app_commands.command(name="unwhitelist_role")
    @app_commands.check(config_check)
    async def unwhitelist_role(self, interaction: discord.Interaction, role: discord.Role):
        assert interaction.guild and database.db
        await database.db.execute("DELETE FROM whitelist_roles WHERE guild_id = ? AND role_id = ?", (interaction.guild.id, role.id))
        await database.db.commit()
        await respond(interaction, f"Роль {role.mention} убрана из whitelist.")

    @app_commands.command(name="whitelist_user")
    @app_commands.check(config_check)
    async def whitelist_user(self, interaction: discord.Interaction, user: discord.User):
        assert interaction.guild and database.db
        await database.db.execute("INSERT OR IGNORE INTO whitelist_users (guild_id, user_id) VALUES (?, ?)", (interaction.guild.id, user.id))
        await database.db.commit()
        await respond(interaction, f"{user.mention} в whitelist.")

    @app_commands.command(name="unwhitelist_user")
    @app_commands.check(config_check)
    async def unwhitelist_user(self, interaction: discord.Interaction, user: discord.User):
        assert interaction.guild and database.db
        await database.db.execute("DELETE FROM whitelist_users WHERE guild_id = ? AND user_id = ?", (interaction.guild.id, user.id))
        await database.db.commit()
        await respond(interaction, f"{user.mention} убран из whitelist.")

    @app_commands.command(name="ban_word")
    @app_commands.check(config_check)
    async def ban_word(self, interaction: discord.Interaction, word: str):
        assert interaction.guild and database.db
        w = word.strip().lower()
        if not w or len(w) < 2:
            await respond(interaction, "Слово слишком короткое.")
            return
        await database.db.execute("INSERT OR IGNORE INTO banned_words (guild_id, word) VALUES (?, ?)", (interaction.guild.id, w))
        await database.db.commit()
        await respond(interaction, f"Слово `{w}` запрещено.")

    @app_commands.command(name="unban_word")
    @app_commands.check(config_check)
    async def unban_word(self, interaction: discord.Interaction, word: str):
        assert interaction.guild and database.db
        w = word.strip().lower()
        await database.db.execute("DELETE FROM banned_words WHERE guild_id = ? AND word = ?", (interaction.guild.id, w))
        await database.db.commit()
        await respond(interaction, f"Слово `{w}` разрешено.")

    @app_commands.command(name="escalation")
    @app_commands.describe(timeout_after="После скольких варнов timeout (0=выкл)", timeout_minutes="Длительность", kick_after="После скольких кик", ban_after="После скольких бан")
    @app_commands.check(config_check)
    async def escalation(self, interaction: discord.Interaction, timeout_after: app_commands.Range[int, 0, 20] = 0, timeout_minutes: app_commands.Range[int, 1, 10080] = 10, kick_after: app_commands.Range[int, 0, 20] = 0, ban_after: app_commands.Range[int, 0, 20] = 0):
        assert interaction.guild and database.db
        await ensure_guild_config(interaction.guild.id)
        await database.db.execute(
            """UPDATE guild_config SET warn_timeout_threshold=?, warn_timeout_minutes=?, warn_kick_threshold=?, warn_ban_threshold=? WHERE guild_id=?""",
            (timeout_after, timeout_minutes, kick_after, ban_after, interaction.guild.id),
        )
        await database.db.commit()
        await respond(interaction, "Эскалация варнов обновлена.")

    @app_commands.command(name="verify")
    @app_commands.check(config_check)
    async def verify_cmd(self, interaction: discord.Interaction, enabled: bool, role: Optional[discord.Role] = None, channel: Optional[discord.TextChannel] = None):
        assert interaction.guild and database.db
        await ensure_guild_config(interaction.guild.id)
        await database.db.execute(
            "UPDATE guild_config SET verify_enabled=?, verify_role_id=COALESCE(?, verify_role_id), verify_channel_id=COALESCE(?, verify_channel_id) WHERE guild_id=?",
            (int(enabled), role.id if role else None, channel.id if channel else None, interaction.guild.id),
        )
        await database.db.commit()
        await respond(interaction, f"Верификация {'включена' if enabled else 'выключена'}.")

    @app_commands.command(name="urlhaus")
    @app_commands.check(config_check)
    async def urlhaus(self, interaction: discord.Interaction, enabled: bool):
        assert interaction.guild and database.db
        await ensure_guild_config(interaction.guild.id)
        await database.db.execute("UPDATE guild_config SET urlhaus_enabled=? WHERE guild_id=?", (int(enabled), interaction.guild.id))
        await database.db.commit()
        note = "" if URLHAUS_AUTH_KEY else " (ключ не задан)"
        await respond(interaction, f"Проверка URLhaus {'включена' if enabled else 'выключена'}.{note}")



    @app_commands.command(name="urlhaus_status", description="Статус кеша URLhaus")
    @app_commands.check(config_check)
    async def urlhaus_status(self, interaction: discord.Interaction):
        from .urlhaus import urlhaus_hosts, urlhaus_urls, urlhaus_last_update, URLHAUS_AUTH_KEY
        import time
        if not URLHAUS_AUTH_KEY:
            await respond(interaction, "URLHAUS_AUTH_KEY не задан.")
            return
        age = int(time.time() - urlhaus_last_update) if urlhaus_last_update else None
        age_s = f"{age} сек назад" if age is not None else "ещё не обновлялся"
        await respond(interaction, f"URLhaus: {len(urlhaus_hosts)} хостов, {len(urlhaus_urls)} URL. Обновление: {age_s}.")

def setup(bot: discord.Client):
    bot.tree.add_command(ConfigGroup())
