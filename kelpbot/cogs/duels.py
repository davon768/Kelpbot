"""Player-vs-player duels: both put up the same bet, a coin decides who takes it all."""

from __future__ import annotations

import asyncio
import random

import discord
from discord import app_commands
from discord.ext import commands

from kelpbot import achievements
from kelpbot.gambling import settle

DUEL_TIMEOUT = 60


class DuelView(discord.ui.View):
    def __init__(self, bot, interaction: discord.Interaction, opponent: discord.Member, bet: int) -> None:
        super().__init__(timeout=DUEL_TIMEOUT)
        self.bot = bot
        self.guild_id = interaction.guild_id
        self.challenger = interaction.user
        self.opponent = opponent
        self.bet = bet
        self.cfg = bot.cfg(interaction.guild_id)
        self.message: discord.InteractionMessage | None = None
        self.done = False

    @property
    def key(self) -> tuple[int, int, str]:
        return (self.guild_id, self.challenger.id, "duel")

    def embed(self, text: str | None = None, color: discord.Color = discord.Color.orange()) -> discord.Embed:
        description = text or (
            f"{self.challenger.mention} challenges {self.opponent.mention} to a duel for "
            f"**{self.cfg.money(self.bet)}** each!\nWinner takes **{self.cfg.money(self.bet * 2)}**. "
            f"Expires in {DUEL_TIMEOUT}s."
        )
        return discord.Embed(title="⚔️ Duel", description=description, color=color)

    def _close(self) -> None:
        self.done = True
        self.bot.active_games.discard(self.key)
        for child in self.children:
            child.disabled = True
        self.stop()
        if self.message:
            self.bot.schedule_cleanup(self.guild_id, self.message.channel.id, self.message.id)

    def _refund(self) -> None:
        self.bot.db.credit(self.guild_id, self.challenger.id, self.bet)

    @discord.ui.button(label="Accept", style=discord.ButtonStyle.success, emoji="⚔️")
    async def accept(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if interaction.user.id != self.opponent.id:
            await interaction.response.send_message("This duel isn't for you.", ephemeral=True)
            return
        if self.done:
            return
        if not self.bot.db.try_debit(self.guild_id, self.opponent.id, self.bet):
            await interaction.response.send_message(
                f"You need {self.cfg.money(self.bet)} in your wallet to accept.", ephemeral=True
            )
            return
        self._close()
        winner, loser = random.sample([self.challenger, self.opponent], 2)
        await interaction.response.edit_message(embed=self.embed("🪙 Flipping..."), view=self)
        await asyncio.sleep(1.5)

        _, unlocked = settle(self.bot, self.guild_id, winner.id, self.bet, self.bet * 2, "duel")
        settle(self.bot, self.guild_id, loser.id, self.bet, 0, "duel")
        self.bot.db.add_event(self.guild_id, "duel", winner.id, self.bet, other_id=loser.id)
        unlocked += achievements.unlock(self.bot.db, self.guild_id, winner.id, "duelist")
        await interaction.edit_original_response(
            embed=self.embed(
                f"🏆 {winner.mention} beat {loser.mention} and won **{self.cfg.money(self.bet * 2)}**!",
                discord.Color.green(),
            ),
            view=self,
        )
        await self.bot.award(interaction, unlocked, winner)

    @discord.ui.button(label="Decline", style=discord.ButtonStyle.danger)
    async def decline(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if interaction.user.id not in (self.opponent.id, self.challenger.id):
            await interaction.response.send_message("This duel isn't for you.", ephemeral=True)
            return
        if self.done:
            return
        self._refund()
        self._close()
        if interaction.user.id == self.opponent.id:
            text = f"{self.opponent.mention} declined the duel."
        else:
            text = f"{self.challenger.mention} called off the duel."
        await interaction.response.edit_message(embed=self.embed(text, discord.Color.light_grey()), view=self)

    async def on_timeout(self) -> None:
        if self.done:
            return
        self._refund()
        self._close()
        if self.message:
            try:
                await self.message.edit(
                    embed=self.embed(f"{self.opponent.mention} didn't answer in time. Bet refunded.",
                                     discord.Color.light_grey()),
                    view=self,
                )
            except discord.HTTPException:
                pass


class Duels(commands.Cog):
    def __init__(self, bot) -> None:
        self.bot = bot

    @app_commands.command(description="Challenge another player: you both bet the same, winner takes all.",
                          extras={"manual_cleanup": True})
    async def duel(self, interaction: discord.Interaction, opponent: discord.Member,
                   bet: app_commands.Range[int, 1]) -> None:
        gid, uid = interaction.guild_id, interaction.user.id
        cfg = self.bot.cfg(gid)
        error = None
        if opponent.bot or opponent.id == uid:
            error = "You can't duel that user."
        elif (gid, uid, "duel") in self.bot.active_games:
            error = "You already have a duel waiting for an answer."
        elif bet < cfg.min_bet or (cfg.max_bet and bet > cfg.max_bet):
            limit = f"{cfg.money(cfg.max_bet)}" if cfg.max_bet else "any amount"
            error = f"Duel bets must be between {cfg.money(cfg.min_bet)} and {limit}."
        elif not self.bot.db.try_debit(gid, uid, bet):  # held until the duel is accepted, declined or expires
            error = f"You need {cfg.money(bet)} in your wallet."
        if error:
            await interaction.response.send_message(error, ephemeral=True)
            return
        view = DuelView(self.bot, interaction, opponent, bet)
        self.bot.active_games.add(view.key)
        await interaction.response.send_message(
            content=opponent.mention, embed=view.embed(), view=view,
            allowed_mentions=discord.AllowedMentions(users=[opponent]),
        )
        view.message = await interaction.original_response()


async def setup(bot) -> None:
    await bot.add_cog(Duels(bot))
