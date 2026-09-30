"""Lottery commands. Draws happen in the scheduler cog."""

from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from kelpbot import config
from kelpbot import lottery as lottery_logic


@app_commands.guild_only()
class Lottery(commands.GroupCog, group_name="lottery"):
    """Buy tickets for the server lottery."""

    def __init__(self, bot) -> None:
        self.bot = bot

    @app_commands.command(description="Buy lottery tickets. More tickets, better odds.")
    async def buy(self, interaction: discord.Interaction,
                  tickets: app_commands.Range[int, 1, config.LOTTERY_MAX_TICKETS] = 1) -> None:
        gid, uid = interaction.guild_id, interaction.user.id
        cfg = self.bot.cfg(gid)
        result = lottery_logic.buy(self.bot.db, gid, uid, tickets, cfg.lottery_ticket_price, interaction.channel_id)
        if result is lottery_logic.BuyResult.TOO_MANY:
            await interaction.response.send_message(
                f"You can hold at most {config.LOTTERY_MAX_TICKETS} tickets per round.", ephemeral=True
            )
            return
        if result is lottery_logic.BuyResult.CANT_AFFORD:
            await interaction.response.send_message(
                f"{tickets} ticket(s) cost {cfg.money(tickets * cfg.lottery_ticket_price)}.", ephemeral=True
            )
            return
        rnd = self.bot.db.lottery_round(gid)
        mine = self.bot.db.lottery_tickets(gid).get(uid, 0)
        await interaction.response.send_message(
            f"🎟️ You bought **{tickets}** ticket(s) for {cfg.money(tickets * cfg.lottery_ticket_price)}. "
            f"You now hold **{mine}**.\nJackpot: **{cfg.money(self._prize(rnd.pot))}** • Draw <t:{int(rnd.draw_at)}:R>"
        )

    @app_commands.command(description="See the jackpot, draw time and your odds.")
    async def info(self, interaction: discord.Interaction) -> None:
        gid = interaction.guild_id
        cfg = self.bot.cfg(gid)
        rnd = self.bot.db.lottery_round(gid)
        embed = discord.Embed(title="🎟️ Lottery", color=discord.Color.gold())
        if rnd is None:
            embed.description = (
                f"No round running. Buy a ticket with `/lottery buy` to start one!\n"
                f"Tickets cost {cfg.money(cfg.lottery_ticket_price)}. The draw happens 24 hours after the first ticket."
            )
        else:
            tickets = self.bot.db.lottery_tickets(gid)
            total = sum(tickets.values())
            mine = tickets.get(interaction.user.id, 0)
            odds = f"{mine / total:.1%}" if total else "0%"
            embed.add_field(name="Jackpot", value=cfg.money(self._prize(rnd.pot)))
            embed.add_field(name="Draw", value=f"<t:{int(rnd.draw_at)}:R>")
            embed.add_field(name="Tickets sold", value=f"{total:,} ({len(tickets)} players)")
            embed.add_field(name="Your tickets", value=f"{mine} ({odds} chance)")
            embed.set_footer(text=f"Tickets cost {cfg.lottery_ticket_price:,}. "
                             f"The winner gets {100 - config.LOTTERY_HOUSE_CUT_PERCENT}% of the pot.")
        await interaction.response.send_message(embed=embed)

    @staticmethod
    def _prize(pot: int) -> int:
        return pot * (100 - config.LOTTERY_HOUSE_CUT_PERCENT) // 100


async def setup(bot) -> None:
    await bot.add_cog(Lottery(bot))
