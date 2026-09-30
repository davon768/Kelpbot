"""Keeps the bot from flooding channels: auto-deletes replies and sweeps old ones."""

from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from kelpbot import config


def fmt_delay(seconds: int) -> str:
    if seconds <= 0:
        return "off"
    if seconds % 3600 == 0:
        return f"{seconds // 3600}h"
    if seconds % 60 == 0:
        return f"{seconds // 60}m"
    return f"{seconds}s"


class Cleanup(commands.Cog):
    def __init__(self, bot) -> None:
        self.bot = bot

    @commands.Cog.listener()
    async def on_app_command_completion(
        self, interaction: discord.Interaction, command: app_commands.Command
    ) -> None:
        if interaction.guild_id is None:
            return
        if interaction.channel_id:
            self.bot.remember_channel(interaction.guild_id, interaction.channel_id)
        if command.extras.get("manual_cleanup"):
            return
        if self.bot.db.auto_delete_seconds(interaction.guild_id) <= 0 or not interaction.response.is_done():
            return
        try:
            message = await interaction.original_response()
        except discord.HTTPException:
            return
        if not message.flags.ephemeral:  # ephemeral replies don't clutter the channel
            self.bot.schedule_cleanup(interaction.guild_id, message.channel.id, message.id)

    @app_commands.command(description="[Mod] Delete the bot's messages from the last N messages in this channel.")
    @app_commands.describe(scan="How many recent messages to look through (default 100)")
    @app_commands.default_permissions(manage_messages=True)
    async def cleanup(self, interaction: discord.Interaction, scan: app_commands.Range[int, 1, 1000] = 100) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        channel = interaction.channel
        # Bulk delete is much faster but needs Manage Messages; without it we delete one at a time.
        bulk = channel.permissions_for(interaction.guild.me).manage_messages
        try:
            deleted = await channel.purge(limit=scan, check=lambda m: m.author.id == self.bot.user.id, bulk=bulk)
        except discord.Forbidden:
            await interaction.followup.send(
                "I need the **Read Message History** permission in this channel to clean it up.", ephemeral=True
            )
            return
        await interaction.followup.send(f"🧹 Deleted **{len(deleted)}** of my messages.", ephemeral=True)

    @app_commands.command(description="[Admin] How long the bot's replies stay before deleting themselves.")
    @app_commands.describe(seconds="Seconds before replies are deleted. 0 turns auto-delete off. Leave empty to see the current setting.")
    @app_commands.default_permissions(manage_guild=True)
    async def autoclean(
        self,
        interaction: discord.Interaction,
        seconds: app_commands.Range[int, 0, config.AUTO_DELETE_MAX_SECONDS] | None = None,
    ) -> None:
        if seconds is None:
            current = self.bot.db.auto_delete_seconds(interaction.guild_id)
            await interaction.response.send_message(f"Auto-delete is **{fmt_delay(current)}**.", ephemeral=True)
            return
        self.bot.db.set_auto_delete_seconds(interaction.guild_id, seconds)
        self.bot.log_event(interaction.guild_id, f"⚙️ <@{interaction.user.id}> set auto-delete to {fmt_delay(seconds)}.")
        if seconds:
            msg = f"✅ My replies will now delete themselves after **{fmt_delay(seconds)}**."
        else:
            msg = "✅ Auto-delete is **off**. Use `/cleanup` to clear old messages by hand."
        await interaction.response.send_message(msg, ephemeral=True)


async def setup(bot) -> None:
    await bot.add_cog(Cleanup(bot))
