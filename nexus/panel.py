from __future__ import annotations

import logging
from datetime import timedelta
from typing import Optional

import discord
from discord import app_commands

from . import database
from .database import (
    ensure_guild_config,
    get_allowed_domains,
    get_banned_words,
    get_config,
    get_ignored_channels,
    get_whitelist_roles,
    get_whitelist_users,
)
from .utils import config_check, moderator_check, respond, send_log
from .verification import VerifyView

log = logging.getLogger("nexus")


def _on_off(v: bool) -> str:
    return "✅" if v else "❌"


class PanelView(discord.ui.View):
    def __init__(self, author_id: int):
        super().__init__(timeout=300)
        self.author_id = author_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("Эта панель не для тебя.", ephemeral=True)
            return False
        return True

    async def build_embed(self, guild: discord.Guild) -> discord.Embed:
        cfg = await get_config(guild.id)
        domains = sorted(await get_allowed_domains(guild.id))
        words = sorted(await get_banned_words(guild.id))
        ignored = await get_ignored_channels(guild.id)
        log_ch = guild.get_channel(cfg["log_channel_id"]) if cfg["log_channel_id"] else None
        log_txt = log_ch.mention if log_ch else (f"`{cfg['log_channel_id']}`" if cfg["log_channel_id"] else "не задан")
        embed = discord.Embed(title="Nexus — Панель управления", color=discord.Color.blurple())
        embed.add_field(name="Канал логов", value=log_txt, inline=True)
        embed.add_field(name="Фильтр ссылок", value=_on_off(cfg["link_filter_enabled"]), inline=True)
        embed.add_field(name="Антифлуд", value=f"{_on_off(cfg['antispam_enabled'])} ({cfg['spam_timeout_minutes']} мин)", inline=True)
        embed.add_field(name="Спам упоминаний", value=_on_off(cfg["mention_spam_enabled"]), inline=True)
        embed.add_field(name="Фильтр слов", value=_on_off(cfg["word_filter_enabled"]), inline=True)
        embed.add_field(name="URLhaus", value=_on_off(cfg.get("urlhaus_enabled", True)), inline=True)
        embed.add_field(name="Верификация", value=_on_off(cfg["verify_enabled"]), inline=True)
        embed.add_field(name="Мин. возраст", value=f"{cfg['min_account_age_days']} дн", inline=True)
        embed.add_field(name="Уведомление ссылок", value=_on_off(cfg["link_notice_enabled"]), inline=True)
        embed.add_field(
            name="Эскалация",
            value=f"timeout {cfg['warn_timeout_threshold']} / kick {cfg['warn_kick_threshold']} / ban {cfg['warn_ban_threshold']}",
            inline=False,
        )
        embed.add_field(name="Домены", value=", ".join(domains) or "нет", inline=False)
        embed.add_field(name="Слова", value=", ".join(words) or "нет", inline=False)
        embed.add_field(name="Игнор-каналы", value=", ".join(f"<#{c}>" for c in ignored) or "нет", inline=False)
        embed.set_footer(text="Кнопки ниже переключают настройки. Для действий над пользователями — вкладка Модерация.")
        return embed

    @discord.ui.button(label="Ссылки", style=discord.ButtonStyle.secondary, row=0)
    async def toggle_links(self, interaction: discord.Interaction, button: discord.ui.Button):
        cfg = await get_config(interaction.guild.id)
        new = 0 if cfg["link_filter_enabled"] else 1
        await database.db.execute("UPDATE guild_config SET link_filter_enabled=? WHERE guild_id=?", (new, interaction.guild.id))
        await interaction.response.edit_message(embed=await self.build_embed(interaction.guild), view=self)

    @discord.ui.button(label="Антифлуд", style=discord.ButtonStyle.secondary, row=0)
    async def toggle_spam(self, interaction: discord.Interaction, button: discord.ui.Button):
        cfg = await get_config(interaction.guild.id)
        new = 0 if cfg["antispam_enabled"] else 1
        await database.db.execute("UPDATE guild_config SET antispam_enabled=? WHERE guild_id=?", (new, interaction.guild.id))
        await interaction.response.edit_message(embed=await self.build_embed(interaction.guild), view=self)

    @discord.ui.button(label="Слова", style=discord.ButtonStyle.secondary, row=0)
    async def toggle_words(self, interaction: discord.Interaction, button: discord.ui.Button):
        cfg = await get_config(interaction.guild.id)
        new = 0 if cfg["word_filter_enabled"] else 1
        await database.db.execute("UPDATE guild_config SET word_filter_enabled=? WHERE guild_id=?", (new, interaction.guild.id))
        await interaction.response.edit_message(embed=await self.build_embed(interaction.guild), view=self)

    @discord.ui.button(label="Упоминания", style=discord.ButtonStyle.secondary, row=0)
    async def toggle_mentions(self, interaction: discord.Interaction, button: discord.ui.Button):
        cfg = await get_config(interaction.guild.id)
        new = 0 if cfg["mention_spam_enabled"] else 1
        await database.db.execute("UPDATE guild_config SET mention_spam_enabled=? WHERE guild_id=?", (new, interaction.guild.id))
        await interaction.response.edit_message(embed=await self.build_embed(interaction.guild), view=self)

    @discord.ui.button(label="URLhaus", style=discord.ButtonStyle.secondary, row=1)
    async def toggle_urlhaus(self, interaction: discord.Interaction, button: discord.ui.Button):
        cfg = await get_config(interaction.guild.id)
        new = 0 if cfg.get("urlhaus_enabled", True) else 1
        await database.db.execute("UPDATE guild_config SET urlhaus_enabled=? WHERE guild_id=?", (new, interaction.guild.id))
        await interaction.response.edit_message(embed=await self.build_embed(interaction.guild), view=self)

    @discord.ui.button(label="Верификация", style=discord.ButtonStyle.secondary, row=1)
    async def toggle_verify(self, interaction: discord.Interaction, button: discord.ui.Button):
        cfg = await get_config(interaction.guild.id)
        new = 0 if cfg["verify_enabled"] else 1
        await database.db.execute("UPDATE guild_config SET verify_enabled=? WHERE guild_id=?", (new, interaction.guild.id))
        await interaction.response.edit_message(embed=await self.build_embed(interaction.guild), view=self)

    @discord.ui.button(label="Увед. ссылок", style=discord.ButtonStyle.secondary, row=1)
    async def toggle_notice(self, interaction: discord.Interaction, button: discord.ui.Button):
        cfg = await get_config(interaction.guild.id)
        new = 0 if cfg["link_notice_enabled"] else 1
        await database.db.execute("UPDATE guild_config SET link_notice_enabled=? WHERE guild_id=?", (new, interaction.guild.id))
        await interaction.response.edit_message(embed=await self.build_embed(interaction.guild), view=self)

    @discord.ui.button(label="Обновить", style=discord.ButtonStyle.primary, row=1)
    async def refresh(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(embed=await self.build_embed(interaction.guild), view=self)

    @discord.ui.button(label="Модерация", style=discord.ButtonStyle.danger, row=2)
    async def open_mod(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = ModActionView(self.author_id)
        await interaction.response.edit_message(content="Выбери действие:", embed=None, view=view)

    @discord.ui.button(label="Списки", style=discord.ButtonStyle.success, row=2)
    async def open_lists(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = ListsView(self.author_id)
        await interaction.response.edit_message(content="Управление списками:", embed=None, view=view)


class ModActionView(discord.ui.View):
    def __init__(self, author_id: int):
        super().__init__(timeout=180)
        self.author_id = author_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("Не твоя панель.", ephemeral=True)
            return False
        if not isinstance(interaction.user, discord.Member) or not (
            interaction.user.guild_permissions.administrator
            or interaction.user.guild_permissions.moderate_members
            or interaction.user.guild_permissions.kick_members
            or interaction.user.guild_permissions.ban_members
        ):
            await interaction.response.send_message("Нет прав модератора.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Варн", style=discord.ButtonStyle.secondary)
    async def do_warn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(UserReasonModal("warn", "Выдать варн"))

    @discord.ui.button(label="Таймаут", style=discord.ButtonStyle.secondary)
    async def do_timeout(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(TimeoutModal())

    @discord.ui.button(label="Кик", style=discord.ButtonStyle.danger)
    async def do_kick(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(UserReasonModal("kick", "Кик"))

    @discord.ui.button(label="Бан", style=discord.ButtonStyle.danger)
    async def do_ban(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(UserReasonModal("ban", "Бан"))

    @discord.ui.button(label="Назад", style=discord.ButtonStyle.primary, row=1)
    async def back(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = PanelView(self.author_id)
        await interaction.response.edit_message(content=None, embed=await view.build_embed(interaction.guild), view=view)


class ListsView(discord.ui.View):
    def __init__(self, author_id: int):
        super().__init__(timeout=180)
        self.author_id = author_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("Не твоя панель.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Добавить домен", style=discord.ButtonStyle.secondary)
    async def add_domain(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(DomainModal(add=True))

    @discord.ui.button(label="Убрать домен", style=discord.ButtonStyle.secondary)
    async def del_domain(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(DomainModal(add=False))

    @discord.ui.button(label="Запретить слово", style=discord.ButtonStyle.secondary)
    async def add_word(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(WordModal(add=True))

    @discord.ui.button(label="Разрешить слово", style=discord.ButtonStyle.secondary)
    async def del_word(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(WordModal(add=False))

    @discord.ui.button(label="Канал логов", style=discord.ButtonStyle.primary, row=1)
    async def set_log(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(LogChannelModal())

    @discord.ui.button(label="Назад", style=discord.ButtonStyle.primary, row=1)
    async def back(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = PanelView(self.author_id)
        await interaction.response.edit_message(content=None, embed=await view.build_embed(interaction.guild), view=view)


class UserReasonModal(discord.ui.Modal):
    user_id = discord.ui.TextInput(label="ID пользователя", placeholder="123456789012345678")
    reason = discord.ui.TextInput(label="Причина", style=discord.TextStyle.paragraph, max_length=500)

    def __init__(self, action: str, title: str):
        super().__init__(title=title)
        self.action = action

    async def on_submit(self, interaction: discord.Interaction):
        if not self.user_id.value.isdigit():
            await interaction.response.send_message("ID должен быть числом.", ephemeral=True)
            return
        uid = int(self.user_id.value)
        member = interaction.guild.get_member(uid)
        reason = self.reason.value[:500]
        try:
            if self.action == "warn":
                if not member:
                    await interaction.response.send_message("Пользователь не на сервере.", ephemeral=True)
                    return
                await database.db.execute(
                    "INSERT INTO warnings (guild_id, user_id, moderator_id, reason, created_at) VALUES (?, ?, ?, ?, datetime('now'))",
                    (interaction.guild.id, uid, interaction.user.id, reason),
                )
                await interaction.response.send_message(f"Варн выдан <@{uid}>.", ephemeral=True)
                await send_log(interaction.guild, "Варн (панель)", f"<@{uid}> от {interaction.user.mention}\n{reason}", color=discord.Color.orange())
            elif self.action == "kick":
                if not member:
                    await interaction.response.send_message("Пользователь не на сервере.", ephemeral=True)
                    return
                await member.kick(reason=f"{interaction.user}: {reason}"[:512])
                await interaction.response.send_message(f"{member} кикнут.", ephemeral=True)
                await send_log(interaction.guild, "Кик (панель)", f"{member} от {interaction.user.mention}\n{reason}", color=discord.Color.red())
            elif self.action == "ban":
                user = member or await interaction.client.fetch_user(uid)
                await interaction.guild.ban(user, reason=f"{interaction.user}: {reason}"[:512])
                await interaction.response.send_message(f"Забанен {user}.", ephemeral=True)
                await send_log(interaction.guild, "Бан (панель)", f"{user} от {interaction.user.mention}\n{reason}", color=discord.Color.red())
        except discord.Forbidden:
            await interaction.response.send_message("Нет прав.", ephemeral=True)


class TimeoutModal(discord.ui.Modal, title="Таймаут"):
    user_id = discord.ui.TextInput(label="ID пользователя")
    minutes = discord.ui.TextInput(label="Минуты", placeholder="10")
    reason = discord.ui.TextInput(label="Причина", required=False)

    async def on_submit(self, interaction: discord.Interaction):
        if not self.user_id.value.isdigit() or not self.minutes.value.isdigit():
            await interaction.response.send_message("ID и минуты — числа.", ephemeral=True)
            return
        member = interaction.guild.get_member(int(self.user_id.value))
        if not member:
            await interaction.response.send_message("Пользователь не на сервере.", ephemeral=True)
            return
        mins = max(1, min(int(self.minutes.value), 40320))
        try:
            await member.timeout(timedelta(minutes=mins), reason=f"{interaction.user}: {self.reason.value}"[:512])
            await interaction.response.send_message(f"Таймаут {mins} мин для {member.mention}.", ephemeral=True)
            await send_log(interaction.guild, "Timeout (панель)", f"{member.mention} на {mins} мин", color=discord.Color.red())
        except discord.Forbidden:
            await interaction.response.send_message("Нет прав.", ephemeral=True)


class DomainModal(discord.ui.Modal):
    domain = discord.ui.TextInput(label="Домен", placeholder="youtube.com")

    def __init__(self, add: bool):
        super().__init__(title="Добавить домен" if add else "Убрать домен")
        self.add = add

    async def on_submit(self, interaction: discord.Interaction):
        d = self.domain.value.strip().lower().rstrip(".")
        if self.add:
            await database.db.execute("INSERT OR IGNORE INTO allowed_domains (guild_id, domain) VALUES (?, ?)", (interaction.guild.id, d))
            await interaction.response.send_message(f"Домен `{d}` разрешён.", ephemeral=True)
        else:
            await database.db.execute("DELETE FROM allowed_domains WHERE guild_id=? AND domain=?", (interaction.guild.id, d))
            await interaction.response.send_message(f"Домен `{d}` убран.", ephemeral=True)


class WordModal(discord.ui.Modal):
    word = discord.ui.TextInput(label="Слово")

    def __init__(self, add: bool):
        super().__init__(title="Запретить слово" if add else "Разрешить слово")
        self.add = add

    async def on_submit(self, interaction: discord.Interaction):
        w = self.word.value.strip().lower()
        if self.add:
            await database.db.execute("INSERT OR IGNORE INTO banned_words (guild_id, word) VALUES (?, ?)", (interaction.guild.id, w))
            await interaction.response.send_message(f"Слово `{w}` запрещено.", ephemeral=True)
        else:
            await database.db.execute("DELETE FROM banned_words WHERE guild_id=? AND word=?", (interaction.guild.id, w))
            await interaction.response.send_message(f"Слово `{w}` разрешено.", ephemeral=True)


class LogChannelModal(discord.ui.Modal, title="Канал логов"):
    channel_id = discord.ui.TextInput(label="ID канала", placeholder="ПКМ по каналу → Копировать ID")

    async def on_submit(self, interaction: discord.Interaction):
        if not self.channel_id.value.isdigit():
            await interaction.response.send_message("ID канала — число.", ephemeral=True)
            return
        cid = int(self.channel_id.value)
        await ensure_guild_config(interaction.guild.id)
        await database.db.execute("UPDATE guild_config SET log_channel_id=? WHERE guild_id=?", (str(cid), interaction.guild.id))
        await interaction.response.send_message(f"Канал логов установлен: <#{cid}>", ephemeral=True)


def setup(bot):
    @bot.tree.command(name="panel", description="Интерактивная панель управления Nexus")
    @app_commands.check(config_check)
    async def panel(interaction: discord.Interaction):
        assert interaction.guild
        view = PanelView(interaction.user.id)
        embed = await view.build_embed(interaction.guild)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
