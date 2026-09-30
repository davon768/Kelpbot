"""Background jobs: lottery draws and the weekly leaderboard payout."""

from __future__ import annotations

import logging
import time

import discord
from discord.ext import commands, tasks

from kelpbot import achievements, lottery, weekly

log = logging.getLogger("kelpbot.scheduler")
MEDALS = ["🥇", "🥈", "🥉"]


class Scheduler(commands.Cog):
    def __init__(self, bot) -> None:
        self.bot = bot
        self.tick.start()

    async def cog_unload(self) -> None:
        self.tick.cancel()

    @tasks.loop(minutes=1)
    async def tick(self) -> None:
        for rnd in self.bot.db.due_lottery_rounds(time.time()):
            try:
                await self.draw_lottery(rnd.guild_id)
            except Exception:
                log.exception("Lottery draw failed for guild %s", rnd.guild_id)
        key = weekly.week_key()
        for guild_id in self.bot.db.guild_ids():
            try:
                winners = weekly.roll_week(self.bot.db, guild_id, key)
                if winners:
                    await self.announce_week(guild_id, winners)
            except Exception:
                log.exception("Weekly rollover failed for guild %s", guild_id)

    @tick.before_loop
    async def _wait_ready(self) -> None:
        await self.bot.wait_until_ready()

    async def draw_lottery(self, guild_id: int) -> None:
        result = lottery.draw(self.bot.db, guild_id)
        if result is None:
            return
        cfg = self.bot.cfg(guild_id)
        unlocked = achievements.unlock(self.bot.db, guild_id, result.winner_id, "lottery_winner")
        text = (
            f"🎉 <@{result.winner_id}> won **{cfg.money(result.prize)}** with {result.winner_tickets} of "
            f"{result.total_tickets} tickets ({result.players} players)!\nA new round starts with the next ticket."
        )
        if unlocked:
            text += f"\n🏅 Achievement unlocked: {unlocked[0].emoji} **{unlocked[0].name}**"
        embed = discord.Embed(title="🎟️ Lottery draw", description=text, color=discord.Color.gold())
        await self.bot.announce(guild_id, embed, fallback_channel_id=result.channel_id)
        self.bot.log_event(guild_id, f"🎟️ <@{result.winner_id}> won the lottery: {cfg.money(result.prize)}.")

    async def announce_week(self, guild_id: int, winners: list[tuple[int, int, int]]) -> None:
        cfg = self.bot.cfg(guild_id)
        lines = [
            f"{MEDALS[i]} <@{uid}>: +{cfg.money(profit)} profit → prize **{cfg.money(prize)}**"
            for i, (uid, profit, prize) in enumerate(winners)
        ]
        embed = discord.Embed(
            title="📈 Weekly winners",
            description="\n".join(lines) + "\n\nThe weekly board has reset. Good luck this week!",
            color=discord.Color.gold(),
        )
        await self.bot.announce(guild_id, embed)


async def setup(bot) -> None:
    await bot.add_cog(Scheduler(bot))
