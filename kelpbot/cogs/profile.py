"""Player-facing progress: profile cards, jobs and daily quests."""

from __future__ import annotations

import time

import discord
from discord import app_commands
from discord.ext import commands

from kelpbot import bank, config, jobs, perks, quests, stocks
from kelpbot.achievements import ACHIEVEMENTS
from kelpbot.tracker import day_start

MONTH = 30 * 24 * 60 * 60


class Profile(commands.Cog):
    def __init__(self, bot) -> None:
        self.bot = bot

    @property
    def db(self):
        return self.bot.db

    @app_commands.command(description="A player's profile card: money, job, pets, favourite game and badges.")
    async def profile(self, interaction: discord.Interaction, user: discord.Member | None = None) -> None:
        target = user or interaction.user
        gid = interaction.guild_id
        cfg = self.bot.cfg(gid)
        bank.accrue(self.db, gid, target.id, cfg.bank_interest_percent)
        acct = self.db.account(gid, target.id)
        portfolio = stocks.portfolio_value(self.db, gid, target.id)
        level = jobs.level_for(acct.work_xp)
        job = jobs.job_for(level)
        ranking = [a.user_id for a in self.db.leaderboard(gid, 1000)]
        rank = f"#{ranking.index(target.id) + 1} of {len(ranking)}" if target.id in ranking else "unranked"

        games = self.db.game_counts(gid, target.id, time.time() - MONTH)
        played = sum(g[1] for g in games)
        won = sum(g[2] for g in games)
        favourite = f"{games[0][0]} ({games[0][1]:,} games)" if games else "none yet"
        owned = self.db.achievements(gid, target.id)
        badges = "".join(a.emoji for a in ACHIEVEMENTS.values() if a.key in owned) or "none yet"
        pet_list = " ".join(p.emoji for p in perks.pets(self.db, gid, target.id)) or "none"

        embed = discord.Embed(title=f"🪪 {target.display_name}", color=discord.Color.gold())
        embed.set_thumbnail(url=target.display_avatar.url)
        embed.add_field(name="💰 Net worth", value=f"{cfg.money(acct.net_worth + portfolio)}\n{rank}")
        embed.add_field(name="👛 Wallet / 🏦 Bank", value=f"{cfg.money(acct.balance)}\n{cfg.money(acct.bank)}")
        embed.add_field(name="📈 Stocks", value=cfg.money(portfolio))
        embed.add_field(name=f"{job.emoji} Job", value=f"{job.name}\nLevel {level} `{jobs.progress_bar(acct.work_xp)}`")
        embed.add_field(name="🎲 Last 30 days",
                        value=f"{played:,} games · {won / played:.0%} won\nFavourite: {favourite}" if played
                        else "No games yet")
        embed.add_field(name="🔥 Streak / Biggest win", value=f"{acct.daily_streak} days\n{cfg.money(acct.biggest_win)}")
        embed.add_field(name="🐾 Pets", value=pet_list)
        embed.add_field(name=f"🏅 Badges ({len(owned)}/{len(ACHIEVEMENTS)})", value=badges, inline=False)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(description="Your job, level and what you unlock next.")
    async def job(self, interaction: discord.Interaction) -> None:
        gid, uid = interaction.guild_id, interaction.user.id
        xp = self.db.account(gid, uid).work_xp
        level = jobs.level_for(xp)
        current = jobs.job_for(level)
        lines = []
        for j in jobs.JOBS:
            mark = "👉" if j == current else ("✅" if j.level <= level else "🔒")
            lines.append(f"{mark} {j.emoji} **{j.name}**: level {j.level}, {j.multiplier}x pay")
        nxt = jobs.next_job(level)
        progress = f"Level **{level}** `{jobs.progress_bar(xp)}` {xp - jobs.xp_for_level(level):,}/" \
                   f"{jobs.xp_for_level(level + 1) - jobs.xp_for_level(level):,} XP"
        if nxt:
            progress += f"\nNext job: {nxt.emoji} {nxt.name} at level {nxt.level}"
        embed = discord.Embed(title=f"{current.emoji} {current.name}", description=progress + "\n\n" + "\n".join(lines),
                              color=discord.Color.blurple())
        embed.set_footer(text="Every /work earns XP. Higher jobs multiply your pay.")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(description="Today's three quests and your progress. Rewards pay out automatically.")
    async def quests(self, interaction: discord.Interaction) -> None:
        gid, uid = interaction.guild_id, interaction.user.id
        cfg = self.bot.cfg(gid)
        lines = []
        for q, progress, done in quests.status(self.db, gid, uid):
            filled = int(8 * progress / q.goal)
            bar = "▰" * filled + "▱" * (8 - filled)
            mark = "✅" if done else q.emoji
            lines.append(f"{mark} **{q.name}**: {q.description}\n`{bar}` {progress:,}/{q.goal:,} · {cfg.money(q.reward)}")
        reset = int(day_start(time.time()) + 24 * 60 * 60)
        embed = discord.Embed(
            title="📋 Daily quests",
            description="\n\n".join(lines) + f"\n\nFinish all three for a **{cfg.money(config.QUEST_ALL_DONE_BONUS)}** "
                        f"bonus. New quests <t:{reset}:R>.",
            color=discord.Color.blurple(),
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot) -> None:
    await bot.add_cog(Profile(bot))
