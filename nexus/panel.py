from __future__ import annotations

import logging
from datetime import timedelta

import discord
from discord import app_commands

from . import database
from .database import (
    ensure_guild_config,
    get_allowed_domains,
    get_banned_words,
    get_config,
    get_ignored_channels,
)
from .utils import config_check, send_log

log = logging.getLogger("nexus")


def on(v: bool) -> str:
    return "Вкл" if v else "Выкл"


class MainPanel(discord.ui.View):
    def __init__(self, author_id: int):
        super().__init__(timeout=600)
        self.author_id = author_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("Это не твоя панель.", ephemeral=True)
            return False
        return True

    async def embed(self, guild: discord.Guild) -> discord.Embed:
        cfg = await get_config(guild.id)
        domains = await get_allowed_domains(guild.id)
        words = await get_banned_words(guild.id)
        ignored = await get_ignored_channels(guild.id)
        ch = guild.get_channel(cfg["log_channel_id"]) if cfg["log_channel_id"] else None
        log_line = ch.mention if ch else "не задан"

        e = discord.Embed(
            title="Nexus",
            description="Панель управления модерацией",
            color=0x2B2D31,
        )
        e.add_field(name="Канал логов", value=log_line, inline=True)
        e.add_field(name="Фильтр ссылок", value=on(cfg["link_filter_enabled"]), inline=True)
        e.add_field(name="Антифлуд", value=f"{on(cfg['antispam_enabled'])} · {cfg['spam_timeout_minutes']} мин", inline=True)
        e.add_field(name="Упоминания", value=on(cfg["mention_spam_enabled"]), inline=True)
        e.add_field(name="Фильтр слов", value=on(cfg["word_filter_enabled"]), inline=True)
        e.add_field(name="URLhaus", value=on(cfg.get("urlhaus_enabled", True)), inline=True)
        e.add_field(name="Верификация", value=on(cfg["verify_enabled"]), inline=True)
        e.add_field(name="Мин. возраст", value=f"{cfg['min_account_age_days']} дн", inline=True)
        e.add_field(name="Увед. о ссылках", value=on(cfg["link_notice_enabled"]), inline=True)
        e.add_field(
            name="Эскалация варнов",
            value=f"timeout ≥{cfg['warn_timeout_threshold']} · kick ≥{cfg['warn_kick_threshold']} · ban ≥{cfg['warn_ban_threshold']}",
            inline=False,
        )
        e.add_field(name=f"Домены ({len(domains)})", value=", ".join(sorted(domains)[:8]) or "—", inline=False)
        e.add_field(name=f"Слова ({len(words)})", value=", ".join(sorted(words)[:8]) or "—", inline=False)
        e.add_field(name=f"Игнор ({len(ignored)})", value=", ".join(f"<#{i}>" for i in list(ignored)[:5]) or "—", inline=False)
        e.set_footer(text="Кнопки переключают модули · Модерация и списки — отдельные экраны")
        return e

    async def refresh(self, interaction: discord.Interaction):
        await interaction.response.defer()
        await interaction.edit_original_response(embed=await self.embed(interaction.guild), view=self)

    @discord.ui.button(label="Ссылки", style=discord.ButtonStyle.secondary, row=0)
    async def b_links(self, i: discord.Interaction, b: discord.ui.Button):
        await i.response.defer()
        cfg = await get_config(i.guild.id)
        await database.db.execute("UPDATE guild_config SET link_filter_enabled=? WHERE guild_id=?", (0 if cfg["link_filter_enabled"] else 1, i.guild.id))
        await i.edit_original_response(embed=await self.embed(i.guild), view=self)

    @discord.ui.button(label="Антифлуд", style=discord.ButtonStyle.secondary, row=0)
    async def b_spam(self, i: discord.Interaction, b: discord.ui.Button):
        await i.response.defer()
        cfg = await get_config(i.guild.id)
        await database.db.execute("UPDATE guild_config SET antispam_enabled=? WHERE guild_id=?", (0 if cfg["antispam_enabled"] else 1, i.guild.id))
        await i.edit_original_response(embed=await self.embed(i.guild), view=self)

    @discord.ui.button(label="Слова", style=discord.ButtonStyle.secondary, row=0)
    async def b_words(self, i: discord.Interaction, b: discord.ui.Button):
        await i.response.defer()
        cfg = await get_config(i.guild.id)
        await database.db.execute("UPDATE guild_config SET word_filter_enabled=? WHERE guild_id=?", (0 if cfg["word_filter_enabled"] else 1, i.guild.id))
        await i.edit_original_response(embed=await self.embed(i.guild), view=self)

    @discord.ui.button(label="Упоминания", style=discord.ButtonStyle.secondary, row=0)
    async def b_ment(self, i: discord.Interaction, b: discord.ui.Button):
        await i.response.defer()
        cfg = await get_config(i.guild.id)
        await database.db.execute("UPDATE guild_config SET mention_spam_enabled=? WHERE guild_id=?", (0 if cfg["mention_spam_enabled"] else 1, i.guild.id))
        await i.edit_original_response(embed=await self.embed(i.guild), view=self)

    @discord.ui.button(label="URLhaus", style=discord.ButtonStyle.secondary, row=1)
    async def b_uh(self, i: discord.Interaction, b: discord.ui.Button):
        await i.response.defer()
        cfg = await get_config(i.guild.id)
        await database.db.execute("UPDATE guild_config SET urlhaus_enabled=? WHERE guild_id=?", (0 if cfg.get("urlhaus_enabled", True) else 1, i.guild.id))
        await i.edit_original_response(embed=await self.embed(i.guild), view=self)

    @discord.ui.button(label="Верификация", style=discord.ButtonStyle.secondary, row=1)
    async def b_ver(self, i: discord.Interaction, b: discord.ui.Button):
        await i.response.defer()
        cfg = await get_config(i.guild.id)
        await database.db.execute("UPDATE guild_config SET verify_enabled=? WHERE guild_id=?", (0 if cfg["verify_enabled"] else 1, i.guild.id))
        await i.edit_original_response(embed=await self.embed(i.guild), view=self)

    @discord.ui.button(label="Увед. ссылок", style=discord.ButtonStyle.secondary, row=1)
    async def b_notice(self, i: discord.Interaction, b: discord.ui.Button):
        await i.response.defer()
        cfg = await get_config(i.guild.id)
        await database.db.execute("UPDATE guild_config SET link_notice_enabled=? WHERE guild_id=?", (0 if cfg["link_notice_enabled"] else 1, i.guild.id))
        await i.edit_original_response(embed=await self.embed(i.guild), view=self)

    @discord.ui.button(label="Обновить", style=discord.ButtonStyle.primary, row=1)
    async def b_ref(self, i: discord.Interaction, b: discord.ui.Button):
        await self.refresh(i)

    @discord.ui.button(label="Модерация", style=discord.ButtonStyle.danger, row=2)
    async def b_mod(self, i: discord.Interaction, b: discord.ui.Button):
        view = ModPanel(self.author_id)
        await i.response.edit_message(embed=view.embed(), view=view)

    @discord.ui.button(label="Списки", style=discord.ButtonStyle.success, row=2)
    async def b_lists(self, i: discord.Interaction, b: discord.ui.Button):
        view = ListPanel(self.author_id)
        await i.response.edit_message(embed=view.embed(), view=view)


class ModPanel(discord.ui.View):
    def __init__(self, author_id: int):
        super().__init__(timeout=300)
        self.author_id = author_id

    def embed(self) -> discord.Embed:
        return discord.Embed(
            title="Модерация",
            description="Выбери действие. Нужен ID пользователя (ПКМ → Копировать ID).",
            color=0xED4245,
        )

    async def interaction_check(self, i: discord.Interaction) -> bool:
        if i.user.id != self.author_id:
            await i.response.send_message("Не твоя панель.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Варн", style=discord.ButtonStyle.secondary)
    async def warn(self, i: discord.Interaction, b: discord.ui.Button):
        await i.response.send_modal(ActionModal("warn", "Варн"))

    @discord.ui.button(label="Таймаут", style=discord.ButtonStyle.secondary)
    async def to(self, i: discord.Interaction, b: discord.ui.Button):
        await i.response.send_modal(TimeoutModal())

    @discord.ui.button(label="Кик", style=discord.ButtonStyle.danger)
    async def kick(self, i: discord.Interaction, b: discord.ui.Button):
        await i.response.send_modal(ActionModal("kick", "Кик"))

    @discord.ui.button(label="Бан", style=discord.ButtonStyle.danger)
    async def ban(self, i: discord.Interaction, b: discord.ui.Button):
        await i.response.send_modal(ActionModal("ban", "Бан"))

    @discord.ui.button(label="Назад", style=discord.ButtonStyle.primary, row=1)
    async def back(self, i: discord.Interaction, b: discord.ui.Button):
        view = MainPanel(self.author_id)
        await i.response.edit_message(embed=await view.embed(i.guild), view=view)


class ListPanel(discord.ui.View):
    def __init__(self, author_id: int):
        super().__init__(timeout=300)
        self.author_id = author_id

    def embed(self) -> discord.Embed:
        return discord.Embed(
            title="Списки и каналы",
            description="Домены, слова, канал логов.",
            color=0x57F287,
        )

    async def interaction_check(self, i: discord.Interaction) -> bool:
        if i.user.id != self.author_id:
            await i.response.send_message("Не твоя панель.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="+ Домен", style=discord.ButtonStyle.secondary)
    async def ad(self, i: discord.Interaction, b: discord.ui.Button):
        await i.response.send_modal(TextModal("domain", True))

    @discord.ui.button(label="− Домен", style=discord.ButtonStyle.secondary)
    async def rd(self, i: discord.Interaction, b: discord.ui.Button):
        await i.response.send_modal(TextModal("domain", False))

    @discord.ui.button(label="+ Слово", style=discord.ButtonStyle.secondary)
    async def aw(self, i: discord.Interaction, b: discord.ui.Button):
        await i.response.send_modal(TextModal("word", True))

    @discord.ui.button(label="− Слово", style=discord.ButtonStyle.secondary)
    async def rw(self, i: discord.Interaction, b: discord.ui.Button):
        await i.response.send_modal(TextModal("word", False))

    @discord.ui.button(label="Канал логов", style=discord.ButtonStyle.primary, row=1)
    async def logch(self, i: discord.Interaction, b: discord.ui.Button):
        await i.response.send_modal(TextModal("log", True))

    @discord.ui.button(label="Назад", style=discord.ButtonStyle.primary, row=1)
    async def back(self, i: discord.Interaction, b: discord.ui.Button):
        view = MainPanel(self.author_id)
        await i.response.edit_message(embed=await view.embed(i.guild), view=view)


class ActionModal(discord.ui.Modal):
    uid = discord.ui.TextInput(label="ID пользователя", placeholder="123456789012345678")
    reason = discord.ui.TextInput(label="Причина", style=discord.TextStyle.paragraph, max_length=400)

    def __init__(self, action: str, title: str):
        super().__init__(title=title)
        self.action = action

    async def on_submit(self, i: discord.Interaction):
        if not self.uid.value.isdigit():
            await i.response.send_message("ID — только цифры.", ephemeral=True)
            return
        uid = int(self.uid.value)
        member = i.guild.get_member(uid)
        reason = self.reason.value[:400]
        try:
            if self.action == "warn":
                if not member:
                    await i.response.send_message("Нет на сервере.", ephemeral=True)
                    return
                await database.db.execute(
                    "INSERT INTO warnings (guild_id, user_id, moderator_id, reason, created_at) VALUES (?, ?, ?, ?, datetime('now'))",
                    (i.guild.id, uid, i.user.id, reason),
                )
                await i.response.send_message(f"Варн → <@{uid}>", ephemeral=True)
                await send_log(i.guild, "Варн", f"<@{uid}> · {i.user.mention}\n{reason}", color=discord.Color.orange())
            elif self.action == "kick" and member:
                await member.kick(reason=f"{i.user}: {reason}"[:512])
                await i.response.send_message(f"Кик → {member}", ephemeral=True)
                await send_log(i.guild, "Кик", f"{member} · {i.user.mention}\n{reason}", color=discord.Color.red())
            elif self.action == "ban":
                user = member or await i.client.fetch_user(uid)
                await i.guild.ban(user, reason=f"{i.user}: {reason}"[:512])
                await i.response.send_message(f"Бан → {user}", ephemeral=True)
                await send_log(i.guild, "Бан", f"{user} · {i.user.mention}\n{reason}", color=discord.Color.red())
            else:
                await i.response.send_message("Пользователь не найден.", ephemeral=True)
        except discord.Forbidden:
            await i.response.send_message("Нет прав.", ephemeral=True)


class TimeoutModal(discord.ui.Modal, title="Таймаут"):
    uid = discord.ui.TextInput(label="ID пользователя")
    minutes = discord.ui.TextInput(label="Минуты", placeholder="10")
    reason = discord.ui.TextInput(label="Причина", required=False)

    async def on_submit(self, i: discord.Interaction):
        if not (self.uid.value.isdigit() and self.minutes.value.isdigit()):
            await i.response.send_message("ID и минуты — числа.", ephemeral=True)
            return
        member = i.guild.get_member(int(self.uid.value))
        if not member:
            await i.response.send_message("Нет на сервере.", ephemeral=True)
            return
        mins = max(1, min(int(self.minutes.value), 40320))
        try:
            await member.timeout(timedelta(minutes=mins), reason=f"{i.user}: {self.reason.value}"[:512])
            await i.response.send_message(f"Таймаут {mins} мин → {member.mention}", ephemeral=True)
            await send_log(i.guild, "Timeout", f"{member.mention} · {mins} мин", color=discord.Color.red())
        except discord.Forbidden:
            await i.response.send_message("Нет прав.", ephemeral=True)


class TextModal(discord.ui.Modal):
    value = discord.ui.TextInput(label="Значение")

    def __init__(self, kind: str, add: bool):
        titles = {
            ("domain", True): "Разрешить домен",
            ("domain", False): "Убрать домен",
            ("word", True): "Запретить слово",
            ("word", False): "Разрешить слово",
            ("log", True): "ID канала логов",
        }
        super().__init__(title=titles.get((kind, add), "Ввод"))
        self.kind = kind
        self.add = add

    async def on_submit(self, i: discord.Interaction):
        v = self.value.value.strip().lower()
        if self.kind == "domain":
            if self.add:
                await database.db.execute("INSERT OR IGNORE INTO allowed_domains (guild_id, domain) VALUES (?, ?)", (i.guild.id, v))
                await i.response.send_message(f"Домен `{v}` добавлен.", ephemeral=True)
            else:
                await database.db.execute("DELETE FROM allowed_domains WHERE guild_id=? AND domain=?", (i.guild.id, v))
                await i.response.send_message(f"Домен `{v}` убран.", ephemeral=True)
        elif self.kind == "word":
            if self.add:
                await database.db.execute("INSERT OR IGNORE INTO banned_words (guild_id, word) VALUES (?, ?)", (i.guild.id, v))
                await i.response.send_message(f"Слово `{v}` запрещено.", ephemeral=True)
            else:
                await database.db.execute("DELETE FROM banned_words WHERE guild_id=? AND word=?", (i.guild.id, v))
                await i.response.send_message(f"Слово `{v}` разрешено.", ephemeral=True)
        elif self.kind == "log":
            if not v.isdigit():
                await i.response.send_message("Нужен числовой ID канала.", ephemeral=True)
                return
            await ensure_guild_config(i.guild.id)
            await database.db.execute("UPDATE guild_config SET log_channel_id=? WHERE guild_id=?", (v, i.guild.id))
            await i.response.send_message(f"Канал логов: <#{v}>", ephemeral=True)


def setup(bot):
    @bot.tree.command(name="panel", description="Панель управления Nexus")
    @app_commands.check(config_check)
    async def panel(interaction: discord.Interaction):
        assert interaction.guild
        view = MainPanel(interaction.user.id)
        await interaction.response.send_message(embed=await view.embed(interaction.guild), view=view, ephemeral=True)
