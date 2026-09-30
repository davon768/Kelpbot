"""Ways to earn, move and view money."""

from __future__ import annotations

import random

import discord
from discord import app_commands
from discord.ext import commands

from kelpbot import config
from kelpbot.config import money
from kelpbot.robbery import RobResult, attempt_rob

JOBS = [
    ("fished for kelp", "🌿"),
    ("delivered pizzas", "🍕"),
    ("walked some dogs", "🐕"),
    ("fixed a leaky faucet", "🔧"),
    ("streamed for 3 viewers", "🎮"),
    ("sold lemonade", "🍋"),
    ("tutored a kid in math", "📐"),
    ("washed cars", "🚗"),
    ("cleaned up the beach", "🏖️"),
]
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


def fmt_duration(seconds: float) -> str:
    seconds = int(seconds) + 1
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    parts = [f"{h}h" if h else "", f"{m}m" if m else "", f"{s}s" if s and not h else ""]
    return " ".join(p for p in parts if p) or "a moment"


@app_commands.guild_only()
class Economy(commands.Cog):
    def __init__(self, bot) -> None:
        self.bot = bot

    @property
    def db(self):
        return self.bot.db

    async def _check_cooldown(self, interaction: discord.Interaction, action: str, cooldown: int) -> bool:
        remaining = self.db.cooldown_remaining(interaction.guild_id, interaction.user.id, action, cooldown)
        if remaining:
            await interaction.response.send_message(
                f"⏳ You can `/{action}` again in **{fmt_duration(remaining)}**.", ephemeral=True
            )
            return False
        return True

    @app_commands.command(description="Check your balance (or someone else's).")
    async def balance(self, interaction: discord.Interaction, user: discord.Member | None = None) -> None:
        target = user or interaction.user
        acct = self.db.account(interaction.guild_id, target.id)
        embed = discord.Embed(title=f"{target.display_name}'s wallet", color=discord.Color.gold())
        embed.add_field(name="Balance", value=money(acct.balance))
        embed.add_field(name="Daily streak", value=f"🔥 {acct.daily_streak}")
        embed.set_thumbnail(url=target.display_avatar.url)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(description="Claim your daily reward. Keep a streak going for a bonus!")
    async def daily(self, interaction: discord.Interaction) -> None:
        gid, uid = interaction.guild_id, interaction.user.id
        if not await self._check_cooldown(interaction, "daily", config.DAILY_COOLDOWN):
            return
        last = self.db.last_used(gid, uid, "daily")
        acct = self.db.account(gid, uid)
        # cooldown_remaining == 0 here, so "still within window" means they kept the streak.
        kept = last is not None and self.db.cooldown_remaining(gid, uid, "daily", config.DAILY_STREAK_WINDOW) > 0
        streak = min(acct.daily_streak + 1, config.DAILY_STREAK_MAX) if kept else 1
        reward = config.DAILY_BASE + config.DAILY_STREAK_BONUS * (streak - 1)

        self.db.mark_used(gid, uid, "daily")
        self.db.set_streak(gid, uid, streak)
        new_balance = self.db.credit(gid, uid, reward)

        msg = f"📅 You claimed **{money(reward)}**! Streak: 🔥 **{streak}**"
        if last is not None and not kept:
            msg += " (your old streak expired)"
        await interaction.response.send_message(f"{msg}\nBalance: {money(new_balance)}")

    @app_commands.command(description="Work an honest shift for some cash.")
    async def work(self, interaction: discord.Interaction) -> None:
        gid, uid = interaction.guild_id, interaction.user.id
        if not await self._check_cooldown(interaction, "work", config.WORK_COOLDOWN):
            return
        pay = random.randint(*config.WORK_PAY)
        job, emoji = random.choice(JOBS)
        self.db.mark_used(gid, uid, "work")
        new_balance = self.db.credit(gid, uid, pay)
        await interaction.response.send_message(
            f"{emoji} You {job} and earned **{money(pay)}**.\nBalance: {money(new_balance)}"
        )

    @app_commands.command(description="Try to steal from another player. Get caught and you pay them a fine.")
    async def rob(self, interaction: discord.Interaction, user: discord.Member) -> None:
        gid, uid = interaction.guild_id, interaction.user.id
        if user.bot or user.id == uid:
            await interaction.response.send_message("You can't rob that user.", ephemeral=True)
            return
        if not await self._check_cooldown(interaction, "rob", config.ROB_COOLDOWN):
            return

        outcome = attempt_rob(self.db, gid, uid, user.id)
        refusals = {
            RobResult.ROBBER_TOO_POOR: f"You need at least {money(config.ROB_MIN_BALANCE)} to rob someone (in case you get caught).",
            RobResult.TARGET_TOO_POOR: f"{user.display_name} has less than {money(config.ROB_MIN_TARGET_BALANCE)}. Not worth it.",
            RobResult.TARGET_PROTECTED: f"{user.display_name} was robbed recently and is on high alert. "
            f"Try again in **{fmt_duration(outcome.protected_for)}**.",
        }
        if outcome.result in refusals:
            await interaction.response.send_message(f"🚫 {refusals[outcome.result]}", ephemeral=True)
            return

        self.db.mark_used(gid, uid, "rob")
        if outcome.result is RobResult.SUCCESS:
            line = random.choice(ROB_SUCCESS).format(victim=user.mention)
            text = f"🦹 {line} and got away with **{money(outcome.amount)}**!"
        else:
            line = random.choice(ROB_FAIL).format(victim=user.mention)
            text = f"🚓 {line}! You paid them **{money(outcome.amount)}** in damages."
        balance = self.db.balance(gid, uid)
        await interaction.response.send_message(
            f"{text}\nBalance: {money(balance)}",
            allowed_mentions=discord.AllowedMentions(users=[user]),
        )

    @app_commands.command(description="Down on your luck? Beg for spare change.")
    async def beg(self, interaction: discord.Interaction) -> None:
        gid, uid = interaction.guild_id, interaction.user.id
        if self.db.balance(gid, uid) > config.BEG_MAX_BALANCE:
            await interaction.response.send_message(
                f"🙄 You can only beg with {money(config.BEG_MAX_BALANCE)} or less.", ephemeral=True
            )
            return
        if not await self._check_cooldown(interaction, "beg", config.BEG_COOLDOWN):
            return
        amount = random.randint(*config.BEG_PAY)
        self.db.mark_used(gid, uid, "beg")
        new_balance = self.db.credit(gid, uid, amount)
        await interaction.response.send_message(
            f"🥺 A kind stranger tossed you **{money(amount)}**.\nBalance: {money(new_balance)}"
        )

    @app_commands.command(description="Give some of your money to another player.")
    async def give(
        self, interaction: discord.Interaction, user: discord.Member, amount: app_commands.Range[int, 1]
    ) -> None:
        if user.bot or user.id == interaction.user.id:
            await interaction.response.send_message("You can't give money to that user.", ephemeral=True)
            return
        if not self.db.transfer(interaction.guild_id, interaction.user.id, user.id, amount):
            await interaction.response.send_message("You don't have that much.", ephemeral=True)
            return
        await interaction.response.send_message(
            f"💸 {interaction.user.mention} gave {user.mention} **{money(amount)}**."
        )

    @app_commands.command(description="The richest players in this server.")
    async def leaderboard(self, interaction: discord.Interaction) -> None:
        top = self.db.leaderboard(interaction.guild_id, 10)
        medals = ["🥇", "🥈", "🥉"]
        lines = [
            f"{medals[i] if i < 3 else f'`#{i + 1}`'} <@{a.user_id}> — {money(a.balance)}"
            for i, a in enumerate(top)
        ]
        embed = discord.Embed(
            title="🏆 Leaderboard",
            description="\n".join(lines) or "Nobody has any money yet!",
            color=discord.Color.gold(),
        )
        await interaction.response.send_message(embed=embed, allowed_mentions=discord.AllowedMentions.none())

    @app_commands.command(description="Your gambling stats.")
    async def stats(self, interaction: discord.Interaction, user: discord.Member | None = None) -> None:
        target = user or interaction.user
        a = self.db.account(interaction.guild_id, target.id)
        embed = discord.Embed(title=f"📊 {target.display_name}'s stats", color=discord.Color.blurple())
        embed.add_field(name="Games played", value=f"{a.games_played:,}")
        embed.add_field(name="Total wagered", value=money(a.total_wagered))
        embed.add_field(name="Net profit", value=f"{'+' if a.net >= 0 else '-'}{money(abs(a.net))}")
        embed.add_field(name="Biggest win", value=money(a.biggest_win))
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="addmoney", description="[Admin] Add or remove money from a player.")
    @app_commands.default_permissions(manage_guild=True)
    async def add_money(self, interaction: discord.Interaction, user: discord.Member, amount: int) -> None:
        new_balance = self.db.credit(interaction.guild_id, user.id, amount)
        await interaction.response.send_message(
            f"✅ Adjusted {user.mention} by {amount:+,}. New balance: {money(new_balance)}", ephemeral=True
        )


async def setup(bot) -> None:
    await bot.add_cog(Economy(bot))
