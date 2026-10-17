from __future__ import annotations

import re
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

import discord
import logging
log = logging.getLogger("nexus")
from discord import app_commands

from .database import get_allowed_domains, get_banned_words, get_config, get_ignored_channels, is_whitelisted
from .urlhaus import URLHAUS_AUTH_KEY, is_urlhaus_malicious
from .utils import bot_deleted_ids, config_check, mark_deleted_by_bot, send_log
from .verification import VerifyView

URL_RE = re.compile(r"(?:https?://|www\.)[^\s<]+", re.IGNORECASE)
WORD_RE = re.compile(r"\b\w+\b", re.IGNORECASE)

SPAM_WINDOW_SECONDS = 7
SPAM_MESSAGE_LIMIT = 5
DUPLICATE_WINDOW_SECONDS = 20
DUPLICATE_LIMIT = 3
MENTION_WINDOW_SECONDS = 10
MENTION_LIMIT = 5

recent_messages: dict[tuple[int, int], deque[float]] = defaultdict(deque)
duplicate_messages: dict[tuple[int, int], deque[tuple[float, str]]] = defaultdict(deque)
mention_counts: dict[tuple[int, int], deque[float]] = defaultdict(deque)



async def notify_user(member: discord.Member, text: str) -> None:
    try:
        dm = member.dm_channel or await member.create_dm()
        await dm.send(text)
        log.info("DM sent to %s", member.id)
    except discord.Forbidden:
        log.warning("Cannot DM %s (forbidden / DMs closed)", member.id)
    except discord.HTTPException as e:
        log.warning("DM to %s failed: %s", member.id, e)


def setup(bot):
    @bot.event
    async def on_member_join(member: discord.Member):
        cfg = await get_config(member.guild.id)
        age = datetime.now(timezone.utc) - member.created_at
        if age < timedelta(days=cfg["min_account_age_days"]):
            await send_log(
                member.guild,
                "Новый аккаунт",
                f"{member.mention} (`{member.id}`) — {age.days} дн. (порог {cfg['min_account_age_days']})",
                color=discord.Color.orange(),
            )
        if cfg["verify_enabled"] and cfg["verify_channel_id"]:
            ch = member.guild.get_channel(cfg["verify_channel_id"])
            if isinstance(ch, discord.TextChannel):
                try:
                    await ch.send(
                        f"{member.mention}, подтверди, что ты не бот, нажав кнопку ниже.",
                        view=VerifyView(),
                        allowed_mentions=discord.AllowedMentions(users=True),
                    )
                except discord.HTTPException:
                    pass

    @bot.event
    async def on_message(message: discord.Message):
        if not message.guild or message.author.bot or not isinstance(message.author, discord.Member):
            return
        if await is_whitelisted(message.author):
            return
        if message.channel.id in await get_ignored_channels(message.guild.id):
            return

        cfg = await get_config(message.guild.id)
        content = message.content or ""

        if cfg["word_filter_enabled"] and content:
            banned = await get_banned_words(message.guild.id)
            if banned and {w.lower() for w in WORD_RE.findall(content)} & banned:
                try:
                    mark_deleted_by_bot(message.id)
                    await message.delete()
                    await send_log(message.guild, "Удалено запрещённое слово", f"{message.author.mention} в {message.channel.mention}\n{discord.utils.escape_markdown(content)[:500]}", color=discord.Color.orange())
                    await notify_user(message.author, f"Твоё сообщение в **{message.guild.name}** удалено: запрещённое слово.")
                except discord.HTTPException:
                    pass
                return

        urls = URL_RE.findall(content) if content else []
        blocked, urlhaus_hit = [], False

        # URLhaus (independent of link filter)
        if cfg.get("urlhaus_enabled") and URLHAUS_AUTH_KEY and urls:
            for raw in urls:
                if is_urlhaus_malicious(raw):
                    urlhaus_hit = True
                    norm = raw.rstrip(".,!?)]}>")
                    if norm not in blocked:
                        blocked.append(norm)

        # Regular link filter
        if cfg["link_filter_enabled"] and urls:
            allowed = await get_allowed_domains(message.guild.id)
            for raw in urls:
                norm = raw.rstrip(".,!?)]}>")
                cand = norm if "://" in norm else "https://" + norm
                try:
                    host = (urlparse(cand).hostname or "").lower().rstrip(".")
                except Exception:
                    host = ""
                if host and not any(host == d or host.endswith("." + d) for d in allowed):
                    if norm not in blocked:
                        blocked.append(norm)

        if blocked:
                try:
                    mark_deleted_by_bot(message.id)
                    await message.delete()
                    title = "Удалена вредоносная ссылка (URLhaus)" if urlhaus_hit else "Удалена ссылка"
                    color = discord.Color.dark_red() if urlhaus_hit else discord.Color.orange()
                    if cfg["link_notice_enabled"]:
                        notice = "обнаружена вредоносная ссылка (URLhaus)." if urlhaus_hit else "ссылки не разрешены."
                        await message.channel.send(f"{message.author.mention}, {notice}", delete_after=8, allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False))
                    await send_log(message.guild, title, f"{message.author.mention} в {message.channel.mention}\n{discord.utils.escape_markdown(content)[:800]}", color=color)
                    dm = "Твоё сообщение удалено: обнаружена вредоносная ссылка." if urlhaus_hit else "Твоё сообщение удалено: ссылки в этом канале не разрешены."
                    await notify_user(message.author, f"{dm} Сервер: **{message.guild.name}**.")
                except discord.HTTPException:
                    pass
                return

        if cfg["antispam_enabled"]:
            key = (message.guild.id, message.author.id)
            now = time.monotonic()
            times = recent_messages[key]
            while times and now - times[0] > SPAM_WINDOW_SECONDS:
                times.popleft()
            times.append(now)
            text = content.strip().casefold()
            dups = duplicate_messages[key]
            while dups and now - dups[0][0] > DUPLICATE_WINDOW_SECONDS:
                dups.popleft()
            if text:
                dups.append((now, text))
            mention_spam = False
            if cfg["mention_spam_enabled"]:
                mtimes = mention_counts[key]
                while mtimes and now - mtimes[0] > MENTION_WINDOW_SECONDS:
                    mtimes.popleft()
                if content.count("<@") + content.count("@everyone") + content.count("@here") >= 2:
                    mtimes.append(now)
                if len(mtimes) >= MENTION_LIMIT:
                    mention_spam = True
            spam = len(times) > SPAM_MESSAGE_LIMIT or (text and sum(1 for _, t in dups if t == text) >= DUPLICATE_LIMIT) or mention_spam
            if spam:
                try:
                    mark_deleted_by_bot(message.id)
                    await message.delete()
                except discord.HTTPException:
                    pass
                tmin = cfg["spam_timeout_minutes"]
                try:
                    await message.author.timeout(timedelta(minutes=tmin), reason="Nexus: антифлуд")
                    await send_log(message.guild, f"Антифлуд ({tmin} мин)", f"{message.author.mention} в {message.channel.mention}", color=discord.Color.red())
                    await notify_user(message.author, f"На сервере **{message.guild.name}** тебе выдан таймаут на {tmin} мин за флуд.")
                except discord.Forbidden:
                    await send_log(message.guild, "Антифлуд: нет прав", f"{message.author.mention}", color=discord.Color.red())
                recent_messages[key].clear()
                duplicate_messages[key].clear()
                mention_counts[key].clear()
                return

    @bot.event
    async def on_message_delete(message: discord.Message):
        if not message.guild or message.author.bot or message.id in bot_deleted_ids:
            if message.id in bot_deleted_ids:
                bot_deleted_ids.discard(message.id)
            return
        text = message.content or "[нет контента]"
        await send_log(message.guild, "Сообщение удалено", f"{message.author.mention} в {message.channel.mention}\n{discord.utils.escape_markdown(text)[:2000]}", color=discord.Color.orange())

    @bot.event
    async def on_message_edit(before: discord.Message, after: discord.Message):
        if not before.guild or before.author.bot or before.content == after.content:
            return
        await send_log(before.guild, "Сообщение изменено", f"{before.author.mention} в {before.channel.mention}\nДо: {discord.utils.escape_markdown(before.content or '')[:600]}\nПосле: {discord.utils.escape_markdown(after.content or '')[:600]}")
