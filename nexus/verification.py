from __future__ import annotations

import discord

from .database import get_config
from .utils import send_log


class VerifyView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Подтвердить", style=discord.ButtonStyle.success, custom_id="nexus_verify")
    async def verify(self, interaction: discord.Interaction, button: discord.ui.Button):
        assert interaction.guild and isinstance(interaction.user, discord.Member)
        cfg = await get_config(interaction.guild.id)
        role_id = cfg["verify_role_id"]
        if not role_id:
            await interaction.response.send_message("Роль верификации не настроена.", ephemeral=True)
            return
        role = interaction.guild.get_role(role_id)
        if not role:
            await interaction.response.send_message("Роль верификации не найдена.", ephemeral=True)
            return
        if role in interaction.user.roles:
            await interaction.response.send_message("Ты уже верифицирован.", ephemeral=True)
            return
        try:
            await interaction.user.add_roles(role, reason="Верификация Nexus")
            await interaction.response.send_message("Верификация пройдена!", ephemeral=True)
            await send_log(
                interaction.guild,
                "Верификация пройдена",
                f"{interaction.user.mention} (`{interaction.user.id}`) получил роль {role.mention}",
                color=discord.Color.green(),
            )
        except discord.Forbidden:
            await interaction.response.send_message("Не хватает прав выдать роль.", ephemeral=True)
