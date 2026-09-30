"""/help: every command, grouped, built from the registered commands so it never goes stale."""

from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

CATEGORIES: dict[str, tuple[str, ...]] = {
    "💰 Earning & saving": ("balance", "daily", "work", "job", "quests", "beg", "rob", "give", "deposit", "withdraw"),
    "🎰 Casino games": ("slots", "blackjack", "coinflip", "roulette", "dice", "crash", "mines", "highlow", "paytable"),
    "👥 Play together": ("duel", "heist", "race", "lottery"),
    "🛒 Shop & stocks": ("shop", "buy", "sell", "use", "inventory", "buyrole", "stocks"),
    "🏆 Progress": ("profile", "stats", "leaderboard", "achievements", "halloffame"),
    "🛠️ Admin": ("settings", "event", "shoprole", "addmoney", "reseteconomy", "endseason", "autoclean", "cleanup",
                 "backup"),
}
ADMIN = "🛠️ Admin"
UNLISTED = {"help"}


def command_lines(tree: app_commands.CommandTree, names: tuple[str, ...]) -> list[str]:
    lines = []
    for name in names:
        cmd = tree.get_command(name)
        if cmd is None:
            continue
        if isinstance(cmd, app_commands.Group):
            lines += [f"`/{name} {sub.name}`: {sub.description}" for sub in cmd.commands]
        else:
            lines.append(f"`/{name}`: {cmd.description}")
    return lines


class HelpView(discord.ui.View):
    def __init__(self, tree: app_commands.CommandTree, categories: list[str]) -> None:
        super().__init__(timeout=300)
        self.tree = tree
        self.select = discord.ui.Select(
            placeholder="Pick a category",
            options=[discord.SelectOption(label=c.split(" ", 1)[1], emoji=c.split(" ", 1)[0], value=c)
                     for c in categories],
        )
        self.select.callback = self.pick
        self.add_item(self.select)

    async def pick(self, interaction: discord.Interaction) -> None:
        category = self.select.values[0]
        embed = discord.Embed(title=category, description="\n".join(command_lines(self.tree, CATEGORIES[category])),
                              color=discord.Color.blurple())
        await interaction.response.edit_message(embed=embed, view=self)


def overview_embed(categories: list[str]) -> discord.Embed:
    embed = discord.Embed(
        title="🎰 Kelpbot help",
        description=(
            "A casino with fake money. Earn it, save it, gamble it, show it off.\n\n"
            "**New here?** Try `/daily`, then `/work`, then `/slots 50`.\n"
            "Check `/quests` every day for bonus coins, and `/profile` to see how you're doing.\n\n"
            "Pick a category below to see its commands."
        ),
        color=discord.Color.blurple(),
    )
    embed.add_field(name="Categories", value="\n".join(categories))
    return embed


class Help(commands.Cog):
    def __init__(self, bot) -> None:
        self.bot = bot

    @app_commands.command(description="Every command, grouped by what it's for.")
    async def help(self, interaction: discord.Interaction) -> None:
        is_admin = bool(interaction.permissions and interaction.permissions.manage_guild)
        categories = [c for c in CATEGORIES if c != ADMIN or is_admin]
        await interaction.response.send_message(embed=overview_embed(categories),
                                                view=HelpView(self.bot.tree, categories), ephemeral=True)


async def setup(bot) -> None:
    await bot.add_cog(Help(bot))
