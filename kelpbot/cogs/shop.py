"""Buying, selling and using items."""

from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from kelpbot import config
from kelpbot.config import money
from kelpbot.shop import ENERGY_DRINK, ITEMS, Kind, TradeResult, buy, sell

ITEM_CHOICES = [app_commands.Choice(name=f"{i.name} ({i.price:,})", value=i.key) for i in ITEMS.values()]
USABLE_CHOICES = [app_commands.Choice(name=i.name, value=i.key) for i in ITEMS.values() if i.kind is Kind.USABLE]


@app_commands.guild_only()
class Shop(commands.Cog):
    def __init__(self, bot) -> None:
        self.bot = bot

    @property
    def db(self):
        return self.bot.db

    @app_commands.command(description="See what's for sale.")
    async def shop(self, interaction: discord.Interaction) -> None:
        embed = discord.Embed(title="🛒 Kelp Mart", color=discord.Color.teal())
        for item in ITEMS.values():
            limit = f" • max {item.max_owned}" if item.max_owned else ""
            embed.add_field(
                name=f"{item.label} — {money(item.price)}",
                value=f"{item.description}\n*{item.kind.value}{limit}*",
                inline=False,
            )
        balance = self.db.balance(interaction.guild_id, interaction.user.id)
        embed.set_footer(text=f"Buy with /buy • Items sell back for half price • Your balance: {balance:,}")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(description="Buy an item from the shop.")
    @app_commands.choices(item=ITEM_CHOICES)
    async def buy(
        self, interaction: discord.Interaction, item: str, quantity: app_commands.Range[int, 1, 100] = 1
    ) -> None:
        gid, uid = interaction.guild_id, interaction.user.id
        it = ITEMS[item]
        result = buy(self.db, gid, uid, item, quantity)
        if result is TradeResult.MAX_OWNED:
            await interaction.response.send_message(
                f"You can only hold {it.max_owned} {it.label}.", ephemeral=True
            )
        elif result is TradeResult.CANT_AFFORD:
            await interaction.response.send_message(
                f"That costs {money(it.price * quantity)} and you have {money(self.db.balance(gid, uid))}.",
                ephemeral=True,
            )
        else:
            await interaction.response.send_message(
                f"🛍️ You bought **{quantity}x {it.label}** for {money(it.price * quantity)}.\n"
                f"Balance: {money(self.db.balance(gid, uid))}"
            )

    @app_commands.command(description="Sell an item back to the shop for half what it cost.")
    @app_commands.choices(item=ITEM_CHOICES)
    async def sell(
        self, interaction: discord.Interaction, item: str, quantity: app_commands.Range[int, 1, 100] = 1
    ) -> None:
        gid, uid = interaction.guild_id, interaction.user.id
        it = ITEMS[item]
        if sell(self.db, gid, uid, item, quantity) is TradeResult.NOT_OWNED:
            await interaction.response.send_message(f"You don't have {quantity}x {it.label}.", ephemeral=True)
            return
        await interaction.response.send_message(
            f"💰 You sold **{quantity}x {it.label}** for {money(it.sell_price * quantity)}.\n"
            f"Balance: {money(self.db.balance(gid, uid))}"
        )

    @app_commands.command(name="use", description="Use an item from your inventory.")
    @app_commands.choices(item=USABLE_CHOICES)
    async def use_item(self, interaction: discord.Interaction, item: str) -> None:
        gid, uid = interaction.guild_id, interaction.user.id
        it = ITEMS[item]
        if item == ENERGY_DRINK.key and not self.db.cooldown_remaining(gid, uid, "work", config.WORK_COOLDOWN):
            await interaction.response.send_message("You can already `/work`. Save it for later!", ephemeral=True)
            return
        if not self.db.remove_item(gid, uid, item):
            await interaction.response.send_message(f"You don't have a {it.label}.", ephemeral=True)
            return
        if item == ENERGY_DRINK.key:
            self.db.clear_cooldown(gid, uid, "work")
            await interaction.response.send_message(f"{it.emoji} Glug glug. You're ready to `/work` again!")

    @app_commands.command(description="See what you (or someone else) own.")
    async def inventory(self, interaction: discord.Interaction, user: discord.Member | None = None) -> None:
        target = user or interaction.user
        owned = self.db.inventory(interaction.guild_id, target.id)
        lines = [f"{ITEMS[k].label} × **{q}**" for k, q in owned.items() if k in ITEMS]
        worth = sum(ITEMS[k].sell_price * q for k, q in owned.items() if k in ITEMS)
        embed = discord.Embed(
            title=f"🎒 {target.display_name}'s inventory",
            description="\n".join(lines) or "Empty. Check out `/shop`!",
            color=discord.Color.teal(),
        )
        if lines:
            embed.set_footer(text=f"Resale value: {worth:,}")
        await interaction.response.send_message(embed=embed)


async def setup(bot) -> None:
    await bot.add_cog(Shop(bot))
