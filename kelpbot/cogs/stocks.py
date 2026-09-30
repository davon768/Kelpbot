"""Stock market commands. Prices move hourly in the scheduler."""

from __future__ import annotations

import time

import discord
from discord import app_commands
from discord.ext import commands

from kelpbot import achievements, config, quests
from kelpbot import stocks as market
from kelpbot.gambling import game_allowed
from kelpbot.tracker import sparkline

STOCK_CHOICES = [app_commands.Choice(name=f"{s.symbol} · {s.name}", value=s.symbol) for s in market.STOCKS.values()]
WOLF_PROFIT = 10_000
DAY = 24 * 60 * 60


def price_sparkline(history: list[tuple[float, float]]) -> str:
    prices = [p for _, p in history[-24:]]
    if len(prices) < 2:
        return ""
    low = min(prices)
    return sparkline([int((p - low) * 100) + 1 for p in prices])


class Stocks(commands.GroupCog, group_name="stocks"):
    """Buy and sell shares in the server's stock market."""

    def __init__(self, bot) -> None:
        self.bot = bot

    @app_commands.command(description="Prices, 24h changes and charts.")
    async def market(self, interaction: discord.Interaction) -> None:
        if not await game_allowed(self.bot, interaction, "stocks"):
            return
        gid = interaction.guild_id
        prices = market.ensure(self.bot.db, gid)
        embed = discord.Embed(title="📈 Kelp Street Exchange", color=discord.Color.teal())
        for s in market.STOCKS.values():
            change = market.change_since(self.bot.db, gid, s.symbol, time.time() - DAY)
            arrow = "" if change is None else f" {'🟢 +' if change >= 0 else '🔴 '}{change:.1f}% (24h)"
            chart = price_sparkline(self.bot.db.stock_history(gid, s.symbol, time.time() - DAY))
            embed.add_field(
                name=f"{s.emoji} {s.symbol} · {s.name}",
                value=f"**{prices[s.symbol]:,.2f}**{arrow}" + (f"\n`{chart}`" if chart else ""),
                inline=True,
            )
        embed.set_footer(text=f"Prices move every hour. Trades have a {config.STOCK_FEE_PERCENT}% fee. "
                              "Use /stocks buy and /stocks sell.")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(description="Buy shares.")
    @app_commands.choices(stock=STOCK_CHOICES)
    async def buy(self, interaction: discord.Interaction, stock: str,
                  shares: app_commands.Range[int, 1, market.MAX_SHARES_PER_TRADE]) -> None:
        if not await game_allowed(self.bot, interaction, "stocks"):
            return
        gid, uid = interaction.guild_id, interaction.user.id
        cfg = self.bot.cfg(gid)
        result, cost = market.buy(self.bot.db, gid, uid, stock, shares)
        if result is market.TradeResult.CANT_AFFORD:
            await interaction.response.send_message(
                f"{shares:,} {stock} costs {cfg.money(cost)} (with fee). Your wallet has "
                f"{cfg.money(self.bot.db.balance(gid, uid))}.", ephemeral=True,
            )
            return
        held = self.bot.db.holdings(gid, uid)[stock][0]
        await interaction.response.send_message(
            f"📈 Bought **{shares:,} {stock}** for {cfg.money(cost)}. You now own {held:,}."
        )
        await self.bot.award(interaction, quests.progress(self.bot.db, gid, uid, "stock_buy"))

    @app_commands.command(description="Sell shares.")
    @app_commands.choices(stock=STOCK_CHOICES)
    async def sell(self, interaction: discord.Interaction, stock: str,
                   shares: app_commands.Range[int, 1, market.MAX_SHARES_PER_TRADE]) -> None:
        if not await game_allowed(self.bot, interaction, "stocks"):
            return
        gid, uid = interaction.guild_id, interaction.user.id
        cfg = self.bot.cfg(gid)
        result, value, profit = market.sell(self.bot.db, gid, uid, stock, shares)
        if result is market.TradeResult.NOT_ENOUGH_SHARES:
            held = self.bot.db.holdings(gid, uid).get(stock, (0, 0))[0]
            await interaction.response.send_message(f"You only own {held:,} {stock}.", ephemeral=True)
            return
        verdict = f"profit **+{cfg.money(profit)}**" if profit >= 0 else f"loss **-{cfg.money(-profit)}**"
        await interaction.response.send_message(
            f"📉 Sold **{shares:,} {stock}** for {cfg.money(value)} ({verdict})."
        )
        if profit >= WOLF_PROFIT:
            await self.bot.award(interaction, achievements.unlock(self.bot.db, gid, uid, "wolf"))

    @app_commands.command(description="Your shares and how they're doing.")
    async def portfolio(self, interaction: discord.Interaction, user: discord.Member | None = None) -> None:
        if not await game_allowed(self.bot, interaction, "stocks"):
            return
        target = user or interaction.user
        gid = interaction.guild_id
        cfg = self.bot.cfg(gid)
        prices = market.ensure(self.bot.db, gid)
        held = self.bot.db.holdings(gid, target.id)
        lines, total, total_cost = [], 0, 0
        for symbol, (shares, cost) in held.items():
            value = int(prices[symbol] * shares)
            total, total_cost = total + value, total_cost + cost
            pl = value - cost
            lines.append(f"{market.STOCKS[symbol].emoji} **{symbol}** × {shares:,} = {cfg.money(value)} "
                         f"({'+' if pl >= 0 else '-'}{cfg.money(abs(pl))})")
        embed = discord.Embed(
            title=f"💼 {target.display_name}'s portfolio",
            description="\n".join(lines) or "No shares yet. See `/stocks market`.",
            color=discord.Color.teal(),
        )
        if lines:
            pl = total - total_cost
            embed.set_footer(text=f"Worth {total:,} · paid {total_cost:,} · {'+' if pl >= 0 else '-'}{abs(pl):,}")
        await interaction.response.send_message(embed=embed)


async def setup(bot) -> None:
    await bot.add_cog(Stocks(bot))
