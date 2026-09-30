"""Heists: a crew buys in together; bigger crews are safer but split the loot more ways."""

from __future__ import annotations

import asyncio
import random

import discord
from discord import app_commands
from discord.ext import commands

from kelpbot import achievements, config
from kelpbot.gambling import game_allowed, settle
from kelpbot.games import heist as odds

STEPS = ("🚐 Pulling up to the Kelp National Bank...", "🔓 Cracking the vault...", "💨 Making a run for it...")
SUCCESS_LINES = ("The getaway boat was waiting. Clean escape!", "Not a single alarm. Legends.")
FAIL_LINES = ("The vault had a second vault. Security got you.", "Someone tripped the laser grid. Busted!")
STEP_SECONDS = 1.2


class HeistView(discord.ui.View):
    def __init__(self, cog: "Heist", interaction: discord.Interaction, bet: int) -> None:
        super().__init__(timeout=None)  # the lobby is timed by the cog, not the view
        self.cog = cog
        self.bot = cog.bot
        self.guild_id = interaction.guild_id
        self.leader = interaction.user
        self.bet = bet
        self.cfg = self.bot.cfg(interaction.guild_id)
        self.crew: dict[int, discord.abc.User] = {}
        self.bet_ids: dict[int, int] = {}
        self.started = False
        self.message: discord.InteractionMessage | None = None
        self.go = asyncio.Event()

    def add_member(self, user: discord.abc.User) -> None:
        self.crew[user.id] = user
        self.bet_ids[user.id] = self.bot.db.open_bet(self.guild_id, user.id, "heist", self.bet)

    def lobby_embed(self) -> discord.Embed:
        n = len(self.crew)
        crew = "\n".join(f"• {u.mention}" for u in self.crew.values())
        if n >= odds.MIN_CREW:
            outlook = (f"Crew of {n}: **{odds.success_chance(n):.0%}** chance, "
                       f"each gets **{odds.multiplier(n)}x** ({self.cfg.money(int(self.bet * odds.multiplier(n)))})")
        else:
            outlook = f"Need at least {odds.MIN_CREW} to go."
        return discord.Embed(
            title="💰 Heist forming!",
            description=f"Buy-in: **{self.cfg.money(self.bet)}**\n{outlook}\n\n**Crew**\n{crew}\n\n"
                        f"Leaves in {config.HEIST_LOBBY_SECONDS}s, or when {self.leader.mention} hits Start.",
            color=discord.Color.dark_gold(),
        )

    @discord.ui.button(label="Join", style=discord.ButtonStyle.success, emoji="🕶️")
    async def join(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        user = interaction.user
        error = None
        if self.started:
            error = "Too late, the crew already left!"
        elif user.id in self.crew:
            error = "You're already in the crew."
        elif len(self.crew) >= config.HEIST_MAX_CREW:
            error = f"The crew is full ({config.HEIST_MAX_CREW} max)."
        elif not self.bot.db.try_debit(self.guild_id, user.id, self.bet):
            error = f"You need {self.cfg.money(self.bet)} in your wallet to join."
        if error:
            await interaction.response.send_message(error, ephemeral=True)
            return
        self.add_member(user)
        await interaction.response.edit_message(embed=self.lobby_embed(), view=self)

    @discord.ui.button(label="Start", style=discord.ButtonStyle.danger, emoji="🚨")
    async def start(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if interaction.user.id != self.leader.id:
            await interaction.response.send_message("Only the heist leader can start it.", ephemeral=True)
            return
        if len(self.crew) < odds.MIN_CREW:
            await interaction.response.send_message(f"You need at least {odds.MIN_CREW} people.", ephemeral=True)
            return
        await interaction.response.defer()
        self.go.set()

    async def edit(self, embed: discord.Embed) -> None:
        if self.message:
            try:
                await self.message.edit(embed=embed, view=self)
            except discord.HTTPException:
                pass

    async def run(self) -> None:
        """Wait for the lobby, then pull the heist (or refund if nobody joined)."""
        try:
            await asyncio.wait_for(self.go.wait(), timeout=config.HEIST_LOBBY_SECONDS)
        except asyncio.TimeoutError:
            pass
        self.started = True
        for child in self.children:
            child.disabled = True
        self.stop()
        n = len(self.crew)
        if n < odds.MIN_CREW:
            for uid, bet_id in self.bet_ids.items():
                self.bot.db.credit(self.guild_id, uid, self.bet)
                self.bot.db.close_bet(bet_id)
            await self.edit(discord.Embed(title="💰 Heist called off",
                                          description="Nobody else joined. Your buy-in was refunded.",
                                          color=discord.Color.light_grey()))
            return

        for step in STEPS:
            await self.edit(discord.Embed(title="💰 Heist in progress", description=step,
                                          color=discord.Color.dark_gold()))
            await asyncio.sleep(STEP_SECONDS)

        success = odds.attempt(n)
        returned = int(self.bet * odds.multiplier(n)) if success else 0
        earned = []
        for uid, user in self.crew.items():
            self.bot.db.close_bet(self.bet_ids[uid])
            _, rewards = settle(self.bot, self.guild_id, uid, self.bet, returned, "heist")
            if success:
                rewards += achievements.unlock(self.bot.db, self.guild_id, uid, "getaway")
            earned += [(user, r) for r in rewards]
        self.bot.db.add_event(self.guild_id, "heist", self.leader.id, returned * n if success else self.bet * n,
                              amount2=n, detail="success" if success else "fail")
        crew = ", ".join(u.mention for u in self.crew.values())
        if success:
            text = (f"{random.choice(SUCCESS_LINES)}\n\nEach of the {n} robbers gets **{self.cfg.money(returned)}** "
                    f"(+{self.cfg.money(returned - self.bet)}).\n{crew}")
            color = discord.Color.green()
        else:
            text = f"{random.choice(FAIL_LINES)}\n\nThe crew lost **{self.cfg.money(self.bet)}** each.\n{crew}"
            color = discord.Color.red()
        if earned:
            text += "\n\n" + "\n".join(f"{r.emoji} {u.mention}: **{r.name}**" for u, r in earned)
        await self.edit(discord.Embed(title="💰 Heist " + ("succeeded!" if success else "failed!"),
                                      description=text, color=color))
        if self.message:
            self.bot.schedule_cleanup(self.guild_id, self.message.channel.id, self.message.id)


class Heist(commands.Cog):
    def __init__(self, bot) -> None:
        self.bot = bot
        self.active: dict[int, HeistView] = {}

    @app_commands.command(description="Start a heist. Others join with the same buy-in; succeed and everyone profits.",
                          extras={"manual_cleanup": True})
    async def heist(self, interaction: discord.Interaction, bet: app_commands.Range[int, 1]) -> None:
        gid, uid = interaction.guild_id, interaction.user.id
        if not await game_allowed(self.bot, interaction, "heist"):
            return
        cfg = self.bot.cfg(gid)
        error = None
        if gid in self.active:
            error = "A heist is already forming. Join that one!"
        elif bet < cfg.min_bet or (cfg.max_bet and bet > cfg.max_bet):
            limit = cfg.money(cfg.max_bet) if cfg.max_bet else "any amount"
            error = f"Buy-ins must be between {cfg.money(cfg.min_bet)} and {limit}."
        elif not self.bot.db.try_debit(gid, uid, bet):
            error = f"You need {cfg.money(bet)} in your wallet."
        if error:
            await interaction.response.send_message(error, ephemeral=True)
            return
        view = HeistView(self, interaction, bet)
        view.add_member(interaction.user)
        self.active[gid] = view
        try:
            await interaction.response.send_message(embed=view.lobby_embed(), view=view)
            view.message = await interaction.original_response()
            await view.run()
        finally:
            self.active.pop(gid, None)


async def setup(bot) -> None:
    await bot.add_cog(Heist(bot))
