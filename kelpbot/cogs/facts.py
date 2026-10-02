"""/funfact and /notsofunfact: post a fact in the channel, never repeating until the list runs out."""

from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from kelpbot import facts

COOLDOWN_SECONDS = 10
NOT_FUN_STYLE = {
    "Sad": ("😢", discord.Color.dark_blue()),
    "Dark": ("💀", discord.Color.dark_grey()),
    "Uninteresting": ("😐", discord.Color.light_grey()),
}


class Facts(commands.Cog):
    def __init__(self, bot) -> None:
        self.bot = bot

    async def _cooldown_ok(self, interaction: discord.Interaction) -> bool:
        # Shared between both commands, so nobody can flood a channel with facts.
        remaining = self.bot.db.cooldown_remaining(interaction.guild_id, interaction.user.id, "fact", COOLDOWN_SECONDS)
        if remaining:
            await interaction.response.send_message(
                f"⏳ Give it {int(remaining) + 1}s before the next fact.", ephemeral=True
            )
            return False
        self.bot.db.mark_used(interaction.guild_id, interaction.user.id, "fact")
        return True

    # Facts stay in the channel: manual_cleanup keeps them out of auto-delete.
    @app_commands.command(description="Post a fun fact. No repeats until you've seen them all.",
                          extras={"manual_cleanup": True})
    async def funfact(self, interaction: discord.Interaction) -> None:
        if not await self._cooldown_ok(interaction):
            return
        fact, number = facts.next_fact(self.bot.db, interaction.guild_id, facts.FUN)
        embed = discord.Embed(title="💡 Fun fact", description=fact.text, color=discord.Color.gold())
        embed.set_footer(text=f"{fact.category} · {number} of {len(facts.FUN.facts)}")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(description="Post a fact that's sad, dark, or deeply uninteresting. No repeats either.",
                          extras={"manual_cleanup": True})
    async def notsofunfact(self, interaction: discord.Interaction) -> None:
        if not await self._cooldown_ok(interaction):
            return
        fact, number = facts.next_fact(self.bot.db, interaction.guild_id, facts.NOT_FUN)
        emoji, color = NOT_FUN_STYLE.get(fact.category, ("😐", discord.Color.light_grey()))
        embed = discord.Embed(title=f"{emoji} Not-so-fun fact", description=fact.text, color=color)
        embed.set_footer(text=f"{fact.category} · {number} of {len(facts.NOT_FUN.facts)}")
        await interaction.response.send_message(embed=embed)


async def setup(bot) -> None:
    await bot.add_cog(Facts(bot))
