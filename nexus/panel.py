from __future__ import annotations

import logging
from datetime import timedelta

import discord
from discord import app_commands

from . import database
from .database import ensure_guild_config, get_allowed_domains, get_banned_words, get_config, get_ignored_channels
from .utils import config_check, send_log

log = logging.getLogger("nexus")


def on(v: bool) -> str:
    return "Вкл" if v else "Выкл"


class MainPanel(discord.ui.View):
    def __init__(self, author_id: int):
        super().__init__(timeout=600)
        self.author_id = author_id
        self.add_item(ModuleSelect(author_id))
        self.add_item(NavSelect(author_id))

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
        e = discord.Embed(title="Nexus", description="Панель управления", color=0x2B2D31)
        e.add_field(name="Канал логов", value=ch.mention if ch else "не задан", inline=True)
        e.add_field(name="Фильтр ссылок", value=on(cfg["link_filter_enabled"]), inline=True)
        e.add_field(name="Антифлуд", value=f"{on(cfg['antispam_enabled'])} · {cfg['spam_timeout_minutes']} мин", inline=True)
        e.add_field(name="Упоминания", value=on(cfg["mention_spam_enabled"]), inline=True)
        e.add_field(name="Фильтр слов", value=on(cfg["word_filter_enabled"]), inline=True)
        e.add_field(name="URLhaus", value=on(cfg.get("urlhaus_enabled", True)), inline=True)
        e.add_field(name="Верификация", value=on(cfg["verify_enabled"]), inline=True)
        e.add_field(name="Мин. возраст", value=f"{cfg['min_account_age_days']} дн", inline=True)
        e.add_field(name="Увед. о ссылках", value=on(cfg["link_notice_enabled"]), inline=True)
        e.add_field(
            name="Эскалация",
            value=f"timeout ≥{cfg['warn_timeout_threshold']} · kick ≥{cfg['warn_kick_threshold']} · ban ≥{cfg['warn_ban_threshold']}",
            inline=False,
        )
        e.add_field(name=f"Домены ({len(domains)})", value=", ".join(sorted(domains)[:6]) or "—", inline=False)
        e.add_field(name=f"Слова ({len(words)})", value=", ".join(sorted(words)[:6]) or "—", inline=False)
        e.set_footer(text="Выбери модуль для переключения или действие ниже")
        return e


class ModuleSelect(discord.ui.Select):
    def __init__(self, author_id: int):
        self.author_id = author_id
        options = [
            discord.SelectOption(label="Фильтр ссылок", value="links", description="Вкл/выкл удаление ссылок"),
            discord.SelectOption(label="Антифлуд", value="spam", description="Вкл/выкл защиту от флуда"),
            discord.SelectOption(label="Фильтр слов", value="words", description="Вкл/выкл чёрный список слов"),
            discord.SelectOption(label="Спам упоминаний", value="mentions", description="Вкл/выкл антиспам @"),
            discord.SelectOption(label="URLhaus", value="urlhaus", description="Проверка вредоносных ссылок"),
            discord.SelectOption(label="Верификация", value="verify", description="Вкл/выкл систему верификации"),
            discord.SelectOption(label="Уведомление о ссылках", value="notice", description="Писать в чат при удалении"),
        ]
        super().__init__(placeholder="Переключить модуль…", options=options, row=0)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        key = self.values[0]
        cfg = await get_config(interaction.guild.id)
        mapping = {
            "links": ("link_filter_enabled", cfg["link_filter_enabled"]),
            "spam": ("antispam_enabled", cfg["antispam_enabled"]),
            "words": ("word_filter_enabled", cfg["word_filter_enabled"]),
            "mentions": ("mention_spam_enabled", cfg["mention_spam_enabled"]),
            "urlhaus": ("urlhaus_enabled", cfg.get("urlhaus_enabled", True)),
            "verify": ("verify_enabled", cfg["verify_enabled"]),
            "notice": ("link_notice_enabled", cfg["link_notice_enabled"]),
        }
        col, current = mapping[key]
        await database.db.execute(f"UPDATE guild_config SET {col}=? WHERE guild_id=?", (0 if current else 1, interaction.guild.id))
        view = MainPanel(self.author_id)
        await interaction.edit_original_response(embed=await view.embed(interaction.guild), view=view)


class NavSelect(discord.ui.Select):
    def __init__(self, author_id: int):
        self.author_id = author_id
        options = [
            discord.SelectOption(label="Модерация", value="mod", description="Варн, таймаут, кик, бан"),
            discord.SelectOption(label="Списки", value="lists", description="Домены, слова, канал логов"),
            discord.SelectOption(label="Обновить", value="refresh", description="Перечитать настройки"),
        ]
        super().__init__(placeholder="Действие…", options=options, row=1)

    async def callback(self, interaction: discord.Interaction):
        choice = self.values[0]
        if choice == "refresh":
            await interaction.response.defer()
            view = MainPanel(self.author_id)
            await interaction.edit_original_response(embed=await view.embed(interaction.guild), view=view)
        elif choice == "mod":
            view = ModPanel(self.author_id)
            await interaction.response.edit_message(embed=view.embed(), view=view)
        elif choice == "lists":
            view = ListPanel(self.author_id)
            await interaction.response.edit_message(embed=view.embed(), view=view)


class ModPanel(discord.ui.View):
    def __init__(self, author_id: int):
        super().__init__(timeout=300)
        self.author_id = author_id
        self.add_item(MemberSelect(author_id))
        self.add_item(BackSelect(author_id))

    def embed(self) -> discord.Embed:
        return discord.Embed(
            title="Модерация",
            description="Выбери пользователя из списка, затем действие.",
            color=0xED4245,
        )

    async def interaction_check(self, i: discord.Interaction) -> bool:
        if i.user.id != self.author_id:
            await i.response.send_message("Не твоя панель.", ephemeral=True)
            return False
        return True


class MemberSelect(discord.ui.UserSelect):
    def __init__(self, author_id: int):
        self.author_id = author_id
        super().__init__(placeholder="Выбери пользователя…", min_values=1, max_values=1)

    async def callback(self, i: discord.Interaction):
        member = self.values[0]
        view = ActionPanel(self.author_id, member)
        await i.response.edit_message(
            embed=discord.Embed(title="Модерация", description=f"Пользователь: {member.mention}", color=0xED4245),
            view=view,
        )


class ActionPanel(discord.ui.View):
    def __init__(self, author_id: int, member: discord.Member):
        super().__init__(timeout=180)
        self.author_id = author_id
        self.member = member
        self.add_item(ActionSelect(author_id, member))

    async def interaction_check(self, i: discord.Interaction) -> bool:
        if i.user.id != self.author_id:
            await i.response.send_message("Не твоя панель.", ephemeral=True)
            return False
        return True


class ActionSelect(discord.ui.Select):
    def __init__(self, author_id: int, member: discord.Member):
        self.author_id = author_id
        self.member = member
        options = [
            discord.SelectOption(label="Варн", value="warn"),
            discord.SelectOption(label="Таймаут", value="timeout"),
            discord.SelectOption(label="Кик", value="kick"),
            discord.SelectOption(label="Бан", value="ban"),
            discord.SelectOption(label="Временный бан", value="tempban"),
            discord.SelectOption(label="← Другой пользователь", value="back"),
        ]
        super().__init__(placeholder="Выбери действие…", options=options)

    async def callback(self, i: discord.Interaction):
        v = self.values[0]
        if v == "back":
            view = ModPanel(self.author_id)
            await i.response.edit_message(embed=view.embed(), view=view)
        elif v == "timeout":
            await i.response.send_modal(TimeoutModal(self.member))
        elif v == "tempban":
            await i.response.send_modal(TempbanModal(self.member))
        else:
            titles = {"warn": "Варн", "kick": "Кик", "ban": "Бан"}
            await i.response.send_modal(ReasonModal(v, titles[v], self.member))


class BackSelect(discord.ui.Select):
    def __init__(self, author_id: int):
        self.author_id = author_id
        super().__init__(placeholder="Навигация…", options=[discord.SelectOption(label="← На главную", value="back")], row=1)

    async def callback(self, i: discord.Interaction):
        view = MainPanel(self.author_id)
        await i.response.edit_message(embed=await view.embed(i.guild), view=view)


class ListPanel(discord.ui.View):
    def __init__(self, author_id: int):
        super().__init__(timeout=300)
        self.author_id = author_id
        self.add_item(ListSelect(author_id))

    def embed(self) -> discord.Embed:
        return discord.Embed(title="Списки", description="Домены, слова, канал логов.", color=0x57F287)

    async def interaction_check(self, i: discord.Interaction) -> bool:
        if i.user.id != self.author_id:
            await i.response.send_message("Не твоя панель.", ephemeral=True)
            return False
        return True


class ListSelect(discord.ui.Select):
    def __init__(self, author_id: int):
        self.author_id = author_id
        options = [
            discord.SelectOption(label="Добавить домен", value="domain_add"),
            discord.SelectOption(label="Убрать домен", value="domain_del"),
            discord.SelectOption(label="Запретить слово", value="word_add"),
            discord.SelectOption(label="Разрешить слово", value="word_del"),
            discord.SelectOption(label="Канал логов", value="log"),
            discord.SelectOption(label="Хаб приватных комнат", value="voice_hub"),
            discord.SelectOption(label="← Назад", value="back"),
        ]
        super().__init__(placeholder="Выбери…", options=options)

    async def callback(self, i: discord.Interaction):
        v = self.values[0]
        if v == "back":
            view = MainPanel(self.author_id)
            await i.response.edit_message(embed=await view.embed(i.guild), view=view)
            return
        kind, add = {
            "domain_add": ("domain", True),
            "domain_del": ("domain", False),
            "word_add": ("word", True),
            "word_del": ("word", False),
            "log": ("log", True),
            "voice_hub": ("voice_hub", True),
        }[v]
        await i.response.send_modal(TextModal(kind, add))


class ReasonModal(discord.ui.Modal):
    reason = discord.ui.TextInput(label="Причина", style=discord.TextStyle.paragraph, max_length=400)

    def __init__(self, action: str, title: str, member: discord.Member):
        super().__init__(title=f"{title}: {member.display_name}")
        self.action = action
        self.member = member

    async def on_submit(self, i: discord.Interaction):
        reason = self.reason.value[:400]
        member = self.member
        try:
            if self.action == "warn":
                await database.db.execute(
                    "INSERT INTO warnings (guild_id, user_id, moderator_id, reason, created_at) VALUES (?, ?, ?, ?, datetime('now'))",
                    (i.guild.id, member.id, i.user.id, reason),
                )
                await i.response.send_message(f"Варн → {member.mention}", ephemeral=True)
                await send_log(i.guild, "Варн", f"{member.mention} · {i.user.mention}\n{reason}", color=discord.Color.orange())
            elif self.action == "kick":
                await member.kick(reason=f"{i.user}: {reason}"[:512])
                await i.response.send_message(f"Кик → {member}", ephemeral=True)
                await send_log(i.guild, "Кик", f"{member} · {i.user.mention}\n{reason}", color=discord.Color.red())
            elif self.action == "ban":
                await i.guild.ban(member, reason=f"{i.user}: {reason}"[:512])
                await i.response.send_message(f"Бан → {member}", ephemeral=True)
                await send_log(i.guild, "Бан", f"{member} · {i.user.mention}\n{reason}", color=discord.Color.red())
        except discord.Forbidden:
            await i.response.send_message("Нет прав.", ephemeral=True)


class TimeoutModal(discord.ui.Modal):
    minutes = discord.ui.TextInput(label="Минуты", placeholder="10")
    reason = discord.ui.TextInput(label="Причина", required=False)

    def __init__(self, member: discord.Member):
        super().__init__(title=f"Таймаут: {member.display_name}")
        self.member = member

    async def on_submit(self, i: discord.Interaction):
        if not self.minutes.value.isdigit():
            await i.response.send_message("Минуты — число.", ephemeral=True)
            return
        mins = max(1, min(int(self.minutes.value), 40320))
        try:
            await self.member.timeout(timedelta(minutes=mins), reason=f"{i.user}: {self.reason.value}"[:512])
            await i.response.send_message(f"Таймаут {mins} мин → {self.member.mention}", ephemeral=True)
            await send_log(i.guild, "Timeout", f"{self.member.mention} · {mins} мин", color=discord.Color.red())
        except discord.Forbidden:
            await i.response.send_message("Нет прав.", ephemeral=True)



class TempbanModal(discord.ui.Modal):
    hours = discord.ui.TextInput(label="Часы", placeholder="24")
    reason = discord.ui.TextInput(label="Причина", style=discord.TextStyle.paragraph, max_length=400)

    def __init__(self, member: discord.Member):
        super().__init__(title=f"Временный бан: {member.display_name}")
        self.member = member

    async def on_submit(self, i: discord.Interaction):
        if not self.hours.value.isdigit():
            await i.response.send_message("Часы — число.", ephemeral=True)
            return
        hours = max(1, min(int(self.hours.value), 720))
        reason = self.reason.value[:400]
        try:
            await i.guild.ban(self.member, reason=f"{i.user}: tempban {hours}h — {reason}"[:512])
            from .moderation import pending_tempbans
            from .database import add_tempban
            import time
            expires = time.time() + hours * 3600
            pending_tempbans[(i.guild.id, self.member.id)] = expires
            await add_tempban(i.guild.id, self.member.id, expires)
            await i.response.send_message(f"Временный бан {hours} ч → {self.member}", ephemeral=True)
            await send_log(i.guild, "Временный бан", f"{self.member} на {hours} ч · {i.user.mention}\n{reason}", color=discord.Color.red())
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
            ("voice_hub", True): "ID голосового хаба",
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
                await i.response.send_message("Нужен числовой ID.", ephemeral=True)
                return
            await ensure_guild_config(i.guild.id)
            await database.db.execute("UPDATE guild_config SET log_channel_id=? WHERE guild_id=?", (v, i.guild.id))
            await i.response.send_message(f"Канал логов: <#{v}>", ephemeral=True)
        elif self.kind == "voice_hub":
            if not v.isdigit():
                await i.response.send_message("Нужен числовой ID голосового канала.", ephemeral=True)
                return
            await database.db.execute(
                "INSERT OR REPLACE INTO voice_config (guild_id, hub_channel_id) VALUES (?, ?)",
                (i.guild.id, v),
            )
            await i.response.send_message(f"Хаб комнат: <#{v}>", ephemeral=True)


def setup(bot):
    @bot.tree.command(name="panel", description="Панель управления Nexus")
    @app_commands.check(config_check)
    async def panel(interaction: discord.Interaction):
        assert interaction.guild
        view = MainPanel(interaction.user.id)
        await interaction.response.send_message(embed=await view.embed(interaction.guild), view=view, ephemeral=True)
