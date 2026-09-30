"""Ways to earn, save, move and view money."""

from __future__ import annotations

import datetime as dt
import random
from typing import Literal

import discord
from discord import app_commands
from discord.ext import commands

from kelpbot import achievements, bank, config, jobs, perks, quests, server_events, stocks
from kelpbot.achievements import ACHIEVEMENTS, COUNTER_GOALS
from kelpbot.robbery import RobResult, attempt_rob
from kelpbot.trust import trust_problem
ROB_SUCCESS = [
    "You picked {victim}'s pocket",
    "You distracted {victim} with a very convincing card trick",
    "You snuck into {victim}'s house through the doggy door",
    "You hustled {victim} at pool",
]
ROB_FAIL = [
    "{victim} caught you red-handed",
    "{victim}'s guard dog chased you off",
    "Your getaway car was a unicycle and {victim} caught up",
    "{victim} was an undercover cop",
]
MEDALS = ["🥇", "🥈", "🥉"]


def fmt_duration(seconds: float) -> str:
    seconds = int(seconds) + 1
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    parts = [f"{h}h" if h else "", f"{m}m" if m else "", f"{s}s" if s and not h else ""]
    return " ".join(p for p in parts if p) or "a moment"


def next_monday_utc() -> int:
    now = dt.datetime.now(dt.timezone.utc)
    monday = (now + dt.timedelta(days=7 - now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    return int(monday.timestamp())


class Economy(commands.Cog):
    def __init__(self, bot) -> None:
        self.bot = bot

    @property
    def db(self):
        return self.bot.db

    async def _check_cooldown(self, interaction: discord.Interaction, action: str, cooldown: float) -> bool:
        remaining = self.db.cooldown_remaining(interaction.guild_id, interaction.user.id, action, cooldown)
        if remaining:
            await interaction.response.send_message(
                f"⏳ You can `/{action}` again in **{fmt_duration(remaining)}**.", ephemeral=True
            )
            return False
        return True

    @app_commands.command(description="Check your wallet and bank (or someone else's).")
    async def balance(self, interaction: discord.Interaction, user: discord.Member | None = None) -> None:
        target = user or interaction.user
        cfg = self.bot.cfg(interaction.guild_id)
        bank.accrue(self.db, interaction.guild_id, target.id, cfg.bank_interest_percent)
        acct = self.db.account(interaction.guild_id, target.id)
        embed = discord.Embed(title=f"{target.display_name}'s {cfg.currency_name}", color=discord.Color.gold())
        embed.add_field(name="👛 Wallet", value=cfg.money(acct.balance))
        embed.add_field(name="🏦 Bank", value=cfg.money(acct.bank))
        embed.add_field(name="💰 Net worth", value=cfg.money(acct.net_worth))
        portfolio = stocks.portfolio_value(self.db, interaction.guild_id, target.id)
        if portfolio:
            embed.add_field(name="📈 Stocks", value=cfg.money(portfolio))
        embed.add_field(name="🔥 Daily streak", value=str(acct.daily_streak))
        embed.set_thumbnail(url=target.display_avatar.url)
        await interaction.response.send_message(embed=embed)
        await self.bot.award(interaction, achievements.check_wealth(self.db, interaction.guild_id, target.id), target)

    @app_commands.command(description="Claim your daily reward. Keep a streak going for a bonus!")
    async def daily(self, interaction: discord.Interaction) -> None:
        gid, uid = interaction.guild_id, interaction.user.id
        cfg = self.bot.cfg(gid)
        if not await self._check_cooldown(interaction, "daily", config.DAILY_COOLDOWN):
            return
        last = self.db.last_used(gid, uid, "daily")
        acct = self.db.account(gid, uid)
        # cooldown_remaining == 0 here, so "still within window" means they kept the streak.
        kept = last is not None and self.db.cooldown_remaining(gid, uid, "daily", config.DAILY_STREAK_WINDOW) > 0
        streak = min(acct.daily_streak + 1, config.DAILY_STREAK_MAX) if kept else 1
        reward = cfg.daily_base + cfg.daily_streak_bonus * (streak - 1)
        reward = int(reward * perks.daily_multiplier(self.db, gid, uid))
        if server_events.is_active(self.db, gid, "double_pay"):
            reward *= 2

        self.db.mark_used(gid, uid, "daily")
        self.db.set_streak(gid, uid, streak)
        new_balance = self.db.credit(gid, uid, reward)

        msg = f"📅 You claimed **{cfg.money(reward)}**! Streak: 🔥 **{streak}**"
        if last is not None and not kept:
            msg += " (your old streak expired)"
        await interaction.response.send_message(f"{msg}\nWallet: {cfg.money(new_balance)}")
        if streak >= config.DAILY_STREAK_MAX:
            await self.bot.award(interaction, achievements.unlock(self.db, gid, uid, "dedicated"))

    @app_commands.command(description="Work a shift. Earn XP to level up into better-paying jobs.")
    async def work(self, interaction: discord.Interaction) -> None:
        gid, uid = interaction.guild_id, interaction.user.id
        cfg = self.bot.cfg(gid)
        if not await self._check_cooldown(interaction, "work", perks.work_cooldown(self.db, gid, uid)):
            return
        old_level = jobs.level_for(self.db.account(gid, uid).work_xp)
        job = jobs.job_for(old_level)
        pay = random.randint(*cfg.work_range) * job.multiplier * perks.work_multiplier(self.db, gid, uid)
        xp = random.randint(*config.WORK_XP)
        notes = []
        if server_events.is_active(self.db, gid, "double_pay"):
            pay *= 2
            notes.append("💼 double pay")
        if server_events.is_active(self.db, gid, "xp_boost"):
            xp *= 2
            notes.append("⭐ double XP")
        pay = int(pay)
        self.db.mark_used(gid, uid, "work")
        new_balance = self.db.credit(gid, uid, pay)
        new_xp = self.db.add_work_xp(gid, uid, xp)
        level = jobs.level_for(new_xp)

        extra = f" ({', '.join(notes)})" if notes else ""
        lines = [f"{job.emoji} You {random.choice(job.shifts)} and earned **{cfg.money(pay)}** and {xp} XP{extra}.",
                 f"Wallet: {cfg.money(new_balance)}"]
        rewards = quests.progress(self.db, gid, uid, "work")
        if level > old_level:
            new_job = jobs.job_for(level)
            lines.append(f"⬆️ **Level {level}!**")
            if new_job != job:
                lines[-1] += f" You've been promoted to **{new_job.emoji} {new_job.name}** ({new_job.multiplier}x pay)."
                self.db.add_event(gid, "promotion", uid, level, detail=new_job.name)
                if new_job == jobs.TOP_JOB:
                    rewards += achievements.unlock(self.db, gid, uid, "tycoon")
        await interaction.response.send_message("\n".join(lines))
        await self.bot.award(interaction, rewards)

    @app_commands.command(description="Try to steal from another player's wallet. Get caught and you pay them a fine.")
    async def rob(self, interaction: discord.Interaction, user: discord.Member) -> None:
        gid, uid = interaction.guild_id, interaction.user.id
        cfg = self.bot.cfg(gid)
        if not cfg.rob_enabled:
            await interaction.response.send_message("🚫 Robbing is turned off in this server.", ephemeral=True)
            return
        if user.bot or user.id == uid:
            await interaction.response.send_message("You can't rob that user.", ephemeral=True)
            return
        if problem := trust_problem(user, cfg):
            await interaction.response.send_message(
                f"🚫 {user.display_name} is too new to rob ({problem}).", ephemeral=True
            )
            return
        if not await self._check_cooldown(interaction, "rob", config.ROB_COOLDOWN):
            return

        outcome = attempt_rob(self.db, gid, uid, user.id)
        refusals = {
            RobResult.ROBBER_TOO_POOR: f"You need at least {cfg.money(config.ROB_MIN_BALANCE)} in your wallet "
            "to rob someone (in case you get caught).",
            RobResult.TARGET_TOO_POOR: f"{user.display_name} has less than {cfg.money(config.ROB_MIN_TARGET_BALANCE)} "
            "in their wallet. Not worth it.",
            RobResult.TARGET_PROTECTED: f"{user.display_name} was robbed recently and is on high alert. "
            f"Try again in **{fmt_duration(outcome.protected_for)}**.",
        }
        if outcome.result in refusals:
            await interaction.response.send_message(f"🚫 {refusals[outcome.result]}", ephemeral=True)
            return

        self.db.mark_used(gid, uid, "rob")
        unlocked = []
        if outcome.result is RobResult.BLOCKED:
            text = f"🔒 {user.mention}'s padlock stopped you cold. It broke, but their wallet's safe."
            self.bot.log_event(gid, f"🔒 <@{uid}> tried to rob <@{user.id}> but hit a padlock.")
        elif outcome.result is RobResult.SUCCESS:
            line = random.choice(ROB_SUCCESS).format(victim=user.mention)
            text = f"🦹 {line} and got away with **{cfg.money(outcome.amount)}**!"
            unlocked = achievements.bump(self.db, gid, uid, "rob_success")
            unlocked += quests.progress(self.db, gid, uid, "rob")
            self.db.add_event(gid, "rob", uid, outcome.amount, other_id=user.id)
            self.bot.log_event(gid, f"🦹 <@{uid}> robbed <@{user.id}> of {cfg.money(outcome.amount)}.")
        else:
            line = random.choice(ROB_FAIL).format(victim=user.mention)
            text = f"🚓 {line}! You paid them **{cfg.money(outcome.amount)}** in damages."
            self.bot.log_event(gid, f"🚓 <@{uid}> got caught robbing <@{user.id}> and paid {cfg.money(outcome.amount)}.")
        if outcome.used_crowbar:
            text += " (🪓 crowbar used)"
        balance = self.db.balance(gid, uid)
        await interaction.response.send_message(
            f"{text}\nWallet: {cfg.money(balance)}",
            allowed_mentions=discord.AllowedMentions(users=[user]),
        )
        await self.bot.award(interaction, unlocked)

    @app_commands.command(description="Down on your luck? Beg for spare change.")
    async def beg(self, interaction: discord.Interaction) -> None:
        gid, uid = interaction.guild_id, interaction.user.id
        cfg = self.bot.cfg(gid)
        acct = self.db.account(gid, uid)
        if acct.net_worth > config.BEG_MAX_BALANCE:
            await interaction.response.send_message(
                f"🙄 You can only beg with {cfg.money(config.BEG_MAX_BALANCE)} or less (wallet + bank).",
                ephemeral=True,
            )
            return
        if not await self._check_cooldown(interaction, "beg", config.BEG_COOLDOWN):
            return
        amount = random.randint(*config.BEG_PAY)
        self.db.mark_used(gid, uid, "beg")
        new_balance = self.db.credit(gid, uid, amount)
        await interaction.response.send_message(
            f"🥺 A kind stranger tossed you **{cfg.money(amount)}**.\nWallet: {cfg.money(new_balance)}"
        )

    @app_commands.command(description="Give some of your wallet money to another player.")
    async def give(
        self, interaction: discord.Interaction, user: discord.Member, amount: app_commands.Range[int, 1]
    ) -> None:
        cfg = self.bot.cfg(interaction.guild_id)
        if user.bot or user.id == interaction.user.id:
            await interaction.response.send_message("You can't give money to that user.", ephemeral=True)
            return
        if problem := trust_problem(interaction.user, cfg):
            await interaction.response.send_message(
                f"🚫 You can't send money yet ({problem}).",
                ephemeral=True,
            )
            return
        if not self.db.transfer(interaction.guild_id, interaction.user.id, user.id, amount):
            await interaction.response.send_message("You don't have that much in your wallet.", ephemeral=True)
            return
        if amount >= config.GIVE_LOG_THRESHOLD:
            self.bot.log_event(interaction.guild_id, f"💸 <@{interaction.user.id}> gave <@{user.id}> {cfg.money(amount)}.")
        await interaction.response.send_message(
            f"💸 {interaction.user.mention} gave {user.mention} **{cfg.money(amount)}**."
        )

    @app_commands.command(description="Put money in the bank: safe from robbers, and it earns daily interest.")
    @app_commands.describe(amount="A number, 'half' or 'all'")
    async def deposit(self, interaction: discord.Interaction, amount: str) -> None:
        gid, uid = interaction.guild_id, interaction.user.id
        cfg = self.bot.cfg(gid)
        value = bank.parse_amount(amount, self.db.balance(gid, uid))
        if not value or not bank.deposit(self.db, gid, uid, value, cfg.bank_interest_percent):
            await interaction.response.send_message(
                f"You can't deposit that. Your wallet has {cfg.money(self.db.balance(gid, uid))}.", ephemeral=True
            )
            return
        acct = self.db.account(gid, uid)
        await interaction.response.send_message(
            f"🏦 Deposited **{cfg.money(value)}**. Bank: {cfg.money(acct.bank)} • Wallet: {cfg.money(acct.balance)}\n"
            f"-# Earns {cfg.bank_interest_percent}% interest per day."
        )
        rewards = achievements.check_wealth(self.db, gid, uid) + quests.progress(self.db, gid, uid, "deposit", value)
        await self.bot.award(interaction, rewards)

    @app_commands.command(description="Take money out of the bank.")
    @app_commands.describe(amount="A number, 'half' or 'all'")
    async def withdraw(self, interaction: discord.Interaction, amount: str) -> None:
        gid, uid = interaction.guild_id, interaction.user.id
        cfg = self.bot.cfg(gid)
        bank.accrue(self.db, gid, uid, cfg.bank_interest_percent)
        value = bank.parse_amount(amount, self.db.account(gid, uid).bank)
        if not value or not bank.withdraw(self.db, gid, uid, value, cfg.bank_interest_percent):
            await interaction.response.send_message(
                f"You can't withdraw that. Your bank has {cfg.money(self.db.account(gid, uid).bank)}.", ephemeral=True
            )
            return
        acct = self.db.account(gid, uid)
        await interaction.response.send_message(
            f"🏦 Withdrew **{cfg.money(value)}**. Bank: {cfg.money(acct.bank)} • Wallet: {cfg.money(acct.balance)}"
        )

    @app_commands.command(description="The richest players, or this week's biggest winners.")
    @app_commands.describe(board="wealth = total net worth, weekly = gambling profit this week (prizes on Monday!)")
    async def leaderboard(
        self, interaction: discord.Interaction, board: Literal["wealth", "weekly"] = "wealth"
    ) -> None:
        gid = interaction.guild_id
        cfg = self.bot.cfg(gid)
        if board == "weekly":
            top = self.db.leaderboard(gid, 10, by="weekly")
            value = lambda a: f"{'+' if a.weekly_profit >= 0 else '-'}{cfg.money(abs(a.weekly_profit))}"  # noqa: E731
            prizes = " / ".join(cfg.money(p) for p in config.WEEKLY_PRIZES)
            title, footer = "📈 This week's biggest winners", f"Top 3 win {prizes}. Resets <t:{next_monday_utc()}:R>."
        else:
            bank.accrue_all(self.db, gid, cfg.bank_interest_percent)
            top = self.db.leaderboard(gid, 10)
            value = lambda a: cfg.money(a.net_worth)  # noqa: E731
            title, footer = "🏆 Richest players", ""
        lines = [
            f"{MEDALS[i] if i < 3 else f'`#{i + 1}`'} <@{a.user_id}>: {value(a)}" for i, a in enumerate(top)
        ]
        description = "\n".join(lines) or "Nobody's on the board yet!"
        if footer:
            description += f"\n\n{footer}"
        embed = discord.Embed(title=title, description=description, color=discord.Color.gold())
        await interaction.response.send_message(embed=embed, allowed_mentions=discord.AllowedMentions.none())

    @app_commands.command(description="Your gambling stats.")
    async def stats(self, interaction: discord.Interaction, user: discord.Member | None = None) -> None:
        target = user or interaction.user
        cfg = self.bot.cfg(interaction.guild_id)
        a = self.db.account(interaction.guild_id, target.id)
        embed = discord.Embed(title=f"📊 {target.display_name}'s stats", color=discord.Color.blurple())
        embed.add_field(name="Games played", value=f"{a.games_played:,}")
        embed.add_field(name="Total wagered", value=cfg.money(a.total_wagered))
        embed.add_field(name="Net profit", value=f"{'+' if a.net >= 0 else '-'}{cfg.money(abs(a.net))}")
        embed.add_field(name="Biggest win", value=cfg.money(a.biggest_win))
        embed.add_field(name="This week", value=f"{'+' if a.weekly_profit >= 0 else '-'}{cfg.money(abs(a.weekly_profit))}")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="achievements", description="See which achievements you (or someone else) have unlocked.")
    async def achievements_cmd(self, interaction: discord.Interaction, user: discord.Member | None = None) -> None:
        target = user or interaction.user
        gid = interaction.guild_id
        cfg = self.bot.cfg(gid)
        owned = self.db.achievements(gid, target.id)
        progress = {key: (counter, goal) for counter, (goal, key) in COUNTER_GOALS.items()}
        lines = []
        for a in ACHIEVEMENTS.values():
            reward = f" · {cfg.money(a.reward)}" if a.reward else ""
            if a.key in owned:
                lines.append(f"✅ {a.emoji} **{a.name}**: {a.description}{reward}")
            else:
                extra = ""
                if a.key in progress:
                    counter, goal = progress[a.key]
                    extra = f" ({min(self.db.counter(gid, target.id, counter), goal)}/{goal})"
                lines.append(f"🔒 {a.name}: {a.description}{extra}{reward}")
        embed = discord.Embed(
            title=f"🏅 {target.display_name}'s achievements ({len(owned)}/{len(ACHIEVEMENTS)})",
            description="\n".join(lines),
            color=discord.Color.gold(),
        )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(description="Winners of past seasons in this server.")
    async def halloffame(self, interaction: discord.Interaction) -> None:
        cfg = self.bot.cfg(interaction.guild_id)
        seasons = self.db.hall_of_fame(interaction.guild_id)
        embed = discord.Embed(title="🏛️ Hall of Fame", color=discord.Color.gold())
        for season, entries in list(seasons.items())[:10]:
            embed.add_field(
                name=f"Season {season}",
                value="\n".join(f"{MEDALS[i]} <@{uid}>: {cfg.money(worth)}" for i, (uid, worth) in enumerate(entries))
                or "No players",
                inline=False,
            )
        if not seasons:
            embed.description = "No seasons have ended yet. Admins can end one with `/endseason`."
        await interaction.response.send_message(embed=embed, allowed_mentions=discord.AllowedMentions.none())


async def setup(bot) -> None:
    await bot.add_cog(Economy(bot))
