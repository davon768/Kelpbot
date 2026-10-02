"""/trivia: a question everyone in the channel can answer for coins."""

from __future__ import annotations

import asyncio
import time

import discord
from discord import app_commands
from discord.ext import commands

from kelpbot import achievements, config, decks, quests
from kelpbot import trivia as bank
from kelpbot.gambling import game_allowed

LETTERS = "ABCD"
TOPIC_CHOICES = [app_commands.Choice(name=label, value=key) for key, label in bank.TOPICS.items()]
DIFFICULTY_STYLE = {"easy": ("🟢", discord.Color.green()), "medium": ("🟡", discord.Color.gold()),
                    "hard": ("🔴", discord.Color.red())}
MEDALS = ["🥇", "🥈", "🥉"]


def earned_key(now: float | None = None) -> str:
    # Stored like quest progress (q:YYYYMMDD:...) so old days are cleaned up automatically.
    return f"q:{quests.day_key(now)}:trivia_earned"


def reward_for(db, guild_id: int, user_id: int, base: int) -> int:
    """Pay up to the daily cap. Returns what was actually paid."""
    earned = db.counter(guild_id, user_id, earned_key())
    paid = max(0, min(base, config.TRIVIA_DAILY_CAP - earned))
    if paid:
        db.credit(guild_id, user_id, paid)
        db.bump_counter(guild_id, user_id, earned_key(), paid)
    return paid


class TriviaView(discord.ui.View):
    def __init__(self, question: bank.Question, options: list[str], correct: int) -> None:
        super().__init__(timeout=None)  # the round is timed by the cog
        self.question = question
        self.options = options
        self.correct = correct
        self.answers: dict[int, tuple[discord.abc.User, int]] = {}  # in the order people answered
        self.closed = False
        self.buttons: list[discord.ui.Button] = []
        for i, option in enumerate(options):
            button = discord.ui.Button(label=f"{LETTERS[i]}. {option}"[:80], style=discord.ButtonStyle.secondary)
            button.callback = self._answer(i)
            self.add_item(button)
            self.buttons.append(button)

    def _answer(self, choice: int):
        async def callback(interaction: discord.Interaction) -> None:
            if self.closed:
                await interaction.response.send_message("Too late, time's up!", ephemeral=True)
                return
            if interaction.user.id in self.answers:
                letter = LETTERS[self.answers[interaction.user.id][1]]
                await interaction.response.send_message(f"You already answered **{letter}**.", ephemeral=True)
                return
            self.answers[interaction.user.id] = (interaction.user, choice)
            await interaction.response.send_message(f"🔒 Locked in **{LETTERS[choice]}**. Results soon!",
                                                    ephemeral=True)
        return callback

    def close(self) -> None:
        self.closed = True
        self.stop()
        for i, button in enumerate(self.buttons):
            button.disabled = True
            if i == self.correct:
                button.style = discord.ButtonStyle.success


class Trivia(commands.Cog):
    def __init__(self, bot) -> None:
        self.bot = bot
        self.active_channels: set[int] = set()

    def question_embed(self, q: bank.Question, ends_at: float, cfg) -> discord.Embed:
        emoji, color = DIFFICULTY_STYLE[q.difficulty]
        reward = config.TRIVIA_REWARDS[q.difficulty]
        embed = discord.Embed(title=f"🧠 Trivia · {q.category}", description=f"**{q.prompt}**", color=color)
        embed.add_field(name="Difficulty", value=f"{emoji} {q.difficulty.capitalize()}")
        embed.add_field(name="Reward", value=f"{cfg.money(reward)} (+{config.TRIVIA_FIRST_BONUS_PERCENT}% if first)")
        embed.add_field(name="Time", value=f"Ends <t:{int(ends_at)}:R>")
        embed.set_footer(text="Everyone gets one answer. Pick a button!")
        return embed

    @app_commands.command(description="Answer a trivia question for coins. Everyone in the channel can play.",
                          extras={"manual_cleanup": True})
    @app_commands.describe(topic="Pick a topic, or leave empty for a random mix")
    @app_commands.choices(topic=TOPIC_CHOICES)
    async def trivia(self, interaction: discord.Interaction, topic: str | None = None) -> None:
        gid, uid = interaction.guild_id, interaction.user.id
        if not await game_allowed(self.bot, interaction, "trivia"):
            return
        if interaction.channel_id in self.active_channels:
            await interaction.response.send_message("A question is already running in this channel!",
                                                    ephemeral=True)
            return
        remaining = self.bot.db.cooldown_remaining(gid, uid, "trivia", config.TRIVIA_START_COOLDOWN)
        if remaining:
            await interaction.response.send_message(f"⏳ You can start another question in {int(remaining) + 1}s.",
                                                    ephemeral=True)
            return
        self.bot.db.mark_used(gid, uid, "trivia")
        topic = topic or bank.pick_topic()
        questions = bank.BY_TOPIC[topic]
        index, _ = decks.next_index(self.bot.db, gid, f"trivia_{topic}", len(questions))
        question = questions[index]
        options, correct = question.options()
        cfg = self.bot.cfg(gid)

        view = TriviaView(question, options, correct)
        ends_at = time.time() + config.TRIVIA_SECONDS
        self.active_channels.add(interaction.channel_id)
        try:
            await interaction.response.send_message(embed=self.question_embed(question, ends_at, cfg), view=view)
            message = await interaction.original_response()
            await asyncio.sleep(config.TRIVIA_SECONDS)
            view.close()
            embed = self.results_embed(gid, question, view, cfg)
            try:
                await message.edit(embed=embed, view=view)
            except discord.HTTPException:
                pass
            self.bot.schedule_cleanup(gid, message.channel.id, message.id)
        finally:
            self.active_channels.discard(interaction.channel_id)

    def results_embed(self, guild_id: int, q: bank.Question, view: TriviaView, cfg) -> discord.Embed:
        db = self.bot.db
        answer = f"{LETTERS[view.correct]}. {view.options[view.correct]}"
        winners = [user for user, choice in view.answers.values() if choice == view.correct]
        wrong = len(view.answers) - len(winners)
        base = config.TRIVIA_REWARDS[q.difficulty]
        lines = [f"**{q.prompt}**", f"✅ The answer was **{answer}**.", ""]
        for place, user in enumerate(winners):
            reward = base + (base * config.TRIVIA_FIRST_BONUS_PERCENT // 100 if place == 0 else 0)
            paid = reward_for(db, guild_id, user.id, reward)
            extras = achievements.bump(db, guild_id, user.id, "trivia_correct")
            extras += quests.progress(db, guild_id, user.id, "trivia")
            note = " (first!)" if place == 0 else ""
            if paid < reward:
                note += " · daily trivia limit reached" if not paid else " · hit the daily trivia limit"
            badges = "".join(f" {r.emoji}" for r in extras)
            medal = MEDALS[place] if place < 3 else "✅"
            lines.append(f"{medal} {user.mention} +{cfg.money(paid)}{note}{badges}")
        if not view.answers:
            lines.append("Nobody answered. 🦗")
        elif not winners:
            lines.append("Nobody got it right this time.")
        if wrong:
            lines.append(f"❌ {wrong} wrong answer{'s' if wrong != 1 else ''}")
        embed = discord.Embed(title=f"🧠 Trivia · {q.category}", description="\n".join(lines),
                              color=discord.Color.green() if winners else discord.Color.red())
        embed.set_footer(text=f"Play again with /trivia · up to {config.TRIVIA_DAILY_CAP:,} coins per day")
        return embed


async def setup(bot) -> None:
    await bot.add_cog(Trivia(bot))
