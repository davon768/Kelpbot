"""Interactive cash-out games: crash, mines and higher or lower."""

from __future__ import annotations

import asyncio
import time

import discord
from discord import app_commands
from discord.ext import commands

from kelpbot import achievements
from kelpbot.gambling import PlayerView, result_line, start_guard, take_bet
from kelpbot.games import crash as crash_game
from kelpbot.games import highlow
from kelpbot.games import mines as mines_game

Bet = app_commands.Range[int, 1]
CRASH_TICK_SECONDS = 1.5
MOON_MULTIPLIER = 10.0
CARD_COUNTER_STREAK = 5


# ---- crash ---------------------------------------------------------------------------

class CrashView(PlayerView):
    game_name = "crash"

    def __init__(self, bot, interaction: discord.Interaction, game: crash_game.CrashGame) -> None:
        super().__init__(bot, interaction, timeout=None)
        self.game = game

    def embed(self) -> discord.Embed:
        g = self.game
        if g.crashed:
            title, color = f"💥 Crashed at {g.crash_at:.2f}x", discord.Color.red()
            text = result_line(self.cfg, g.bet, 0)[0]
        elif g.cashed_out:
            title, color = f"🚀 Cashed out at {g.cashed_out:.2f}x", discord.Color.green()
            text = result_line(self.cfg, g.bet, g.payout())[0] + f"\nIt crashed at **{g.crash_at:.2f}x**."
        else:
            m = g.current(time.monotonic())
            title, color = f"🚀 {m:.2f}x", discord.Color.blurple()
            text = f"Cash out now for **{self.cfg.money(int(g.bet * m))}**"
            if g.auto_cashout:
                text += f"\nAuto cash-out at **{g.auto_cashout:.2f}x**"
        e = discord.Embed(title=title, description=text, color=color)
        footer = f"Bet: {g.bet:,}"
        if self.settled:
            footer += f" • Wallet: {self.balance:,}"
        e.set_footer(text=footer)
        return e

    def settle_if_done(self) -> list | None:
        if not self.game.finished:
            return None
        unlocked = self.finalize(self.game.bet, self.game.payout())
        if unlocked is not None and (self.game.cashed_out or 0) >= MOON_MULTIPLIER:
            unlocked += achievements.unlock(self.bot.db, self.guild_id, self.player.id, "to_the_moon")
        return unlocked

    @discord.ui.button(label="Cash Out", style=discord.ButtonStyle.success, emoji="💰")
    async def cash(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        self.game.cash_out(time.monotonic())
        unlocked = self.settle_if_done()
        await interaction.response.edit_message(embed=self.embed(), view=self)
        await self.bot.award(interaction, unlocked or [])


# ---- mines ---------------------------------------------------------------------------

class MinesView(PlayerView):
    game_name = "mines"

    def __init__(self, bot, interaction: discord.Interaction, game: mines_game.MinesGame) -> None:
        super().__init__(bot, interaction)
        self.game = game
        self.tiles: list[discord.ui.Button] = []
        for i in range(mines_game.TILES):
            button = discord.ui.Button(label="​", style=discord.ButtonStyle.secondary, row=i // 5)
            button.callback = self._tile_callback(i)
            self.add_item(button)
            self.tiles.append(button)
        self.cash = discord.ui.Button(style=discord.ButtonStyle.success, emoji="💰", row=4)
        self.cash.callback = self._cash_out
        self.add_item(self.cash)
        self._render()

    def _render(self) -> None:
        g = self.game
        for i, button in enumerate(self.tiles):
            if i in g.revealed:
                button.emoji, button.label, button.style, button.disabled = "💎", None, discord.ButtonStyle.success, True
            elif g.finished and i in g.mine_tiles:
                button.emoji, button.label = "💣", None
                button.style = discord.ButtonStyle.danger
        self.cash.label = f"Cash Out {self.cfg.money(int(g.bet * g.current_multiplier))}"
        self.cash.disabled = not g.revealed or g.finished
        if g.finished:
            self.disable_all()

    def embed(self) -> discord.Embed:
        g = self.game
        if g.exploded:
            title, color, text = "💥 Boom!", discord.Color.red(), result_line(self.cfg, g.bet, 0)[0]
        elif g.cashed_out:
            title, color = f"💎 Cashed out at {g.current_multiplier:.2f}x", discord.Color.green()
            text = result_line(self.cfg, g.bet, g.payout())[0]
        else:
            title, color = f"💣 Mines ({g.mines} hidden)", discord.Color.blurple()
            text = (f"Current: **{g.current_multiplier:.2f}x** • Next safe tile: **{g.next_multiplier:.2f}x**\n"
                    "Pick a tile, or cash out.")
        e = discord.Embed(title=title, description=text, color=color)
        footer = f"Bet: {g.bet:,}"
        if self.settled:
            footer += f" • Wallet: {self.balance:,}"
        e.set_footer(text=footer)
        return e

    def _settle(self) -> list:
        unlocked = self.finalize(self.game.bet, self.game.payout()) or []
        if self.game.cleared:
            unlocked += achievements.unlock(self.bot.db, self.guild_id, self.player.id, "minesweeper")
        return unlocked

    def _tile_callback(self, tile: int):
        async def callback(interaction: discord.Interaction) -> None:
            self.game.reveal(tile)
            unlocked = self._settle() if self.game.finished else []
            self._render()
            await interaction.response.edit_message(embed=self.embed(), view=self)
            await self.bot.award(interaction, unlocked)
        return callback

    async def _cash_out(self, interaction: discord.Interaction) -> None:
        unlocked = self._settle() if self.game.cash_out() else []
        self._render()
        await interaction.response.edit_message(embed=self.embed(), view=self)
        await self.bot.award(interaction, unlocked)

    async def on_timeout(self) -> None:
        # Walked away: keep what they've won so far (or get the bet back if they never picked).
        if not self.game.finished:
            self.game.cashed_out = True
            self._settle()
            self._render()
            if self.message:
                try:
                    await self.message.edit(embed=self.embed(), view=self)
                except discord.HTTPException:
                    pass


# ---- higher or lower ----------------------------------------------------------------------

class HighLowView(PlayerView):
    game_name = "higher or lower"

    def __init__(self, bot, interaction: discord.Interaction, game: highlow.HighLowGame) -> None:
        super().__init__(bot, interaction)
        self.game = game
        self._render()

    def _render(self) -> None:
        g = self.game
        for button, higher in ((self.higher, True), (self.lower, False)):
            step = highlow.guess_multiplier(g.card, higher)
            button.label = f"{'Higher' if higher else 'Lower'} ({step:.2f}x)" if step else ("Higher" if higher else "Lower")
            button.disabled = step is None or g.finished
        self.cash.label = f"Cash Out {self.cfg.money(int(g.bet * g.multiplier))}"
        self.cash.disabled = g.streak == 0 or g.finished
        if g.finished:
            self.disable_all()

    def embed(self) -> discord.Embed:
        g = self.game
        card = f"**{highlow.label(g.card)}**"
        if g.lost:
            title, color = "❌ Wrong!", discord.Color.red()
            text = f"{highlow.label(g.previous)} → {card}\n\n" + result_line(self.cfg, g.bet, 0)[0]
        elif g.cashed_out:
            title, color = f"💰 Cashed out at {g.multiplier:.2f}x", discord.Color.green()
            text = result_line(self.cfg, g.bet, g.payout())[0]
        else:
            title, color = "🔮 Higher or Lower", discord.Color.blurple()
            prev = f"{highlow.label(g.previous)} → " if g.previous else ""
            text = (f"Card: {prev}{card}\nMultiplier: **{g.multiplier:.2f}x** • Streak: **{g.streak}**\n"
                    "Will the next card (A-K) be higher or lower? Ties lose.")
        e = discord.Embed(title=title, description=text, color=color)
        footer = f"Bet: {g.bet:,}"
        if self.settled:
            footer += f" • Wallet: {self.balance:,}"
        e.set_footer(text=footer)
        return e

    def _settle(self) -> list:
        unlocked = self.finalize(self.game.bet, self.game.payout()) or []
        if self.game.streak >= CARD_COUNTER_STREAK:
            unlocked += achievements.unlock(self.bot.db, self.guild_id, self.player.id, "card_counter")
        return unlocked

    async def _after(self, interaction: discord.Interaction) -> None:
        unlocked = self._settle() if self.game.finished else []
        if self.game.streak >= CARD_COUNTER_STREAK and not self.game.finished:
            unlocked = achievements.unlock(self.bot.db, self.guild_id, self.player.id, "card_counter")
        self._render()
        await interaction.response.edit_message(embed=self.embed(), view=self)
        await self.bot.award(interaction, unlocked)

    @discord.ui.button(label="Higher", style=discord.ButtonStyle.primary, emoji="⬆️")
    async def higher(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        self.game.guess(True)
        await self._after(interaction)

    @discord.ui.button(label="Lower", style=discord.ButtonStyle.primary, emoji="⬇️")
    async def lower(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        self.game.guess(False)
        await self._after(interaction)

    @discord.ui.button(label="Cash Out", style=discord.ButtonStyle.success, emoji="💰")
    async def cash(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        self.game.cash_out()
        await self._after(interaction)

    async def on_timeout(self) -> None:
        if not self.game.finished:
            self.game.cashed_out = True  # keep winnings so far, or refund if no guesses yet
            self._settle()
            self._render()
            if self.message:
                try:
                    await self.message.edit(embed=self.embed(), view=self)
                except discord.HTTPException:
                    pass


class Arcade(commands.Cog):
    def __init__(self, bot) -> None:
        self.bot = bot

    async def _start(self, interaction: discord.Interaction, view: PlayerView) -> None:
        self.bot.active_games.add(view.key)
        view.track_bet(view.game.bet)
        await interaction.response.send_message(embed=view.embed(), view=view)
        view.message = await interaction.original_response()

    @app_commands.command(description="A multiplier climbs until it crashes. Cash out before it does!",
                          extras={"manual_cleanup": True})
    @app_commands.describe(auto_cashout="Cash out automatically at this multiplier, e.g. 2.5")
    async def crash(
        self,
        interaction: discord.Interaction,
        bet: Bet,
        auto_cashout: app_commands.Range[float, 1.01, crash_game.MAX_MULTIPLIER] | None = None,
    ) -> None:
        if not await start_guard(self.bot, interaction, "crash") or not await take_bet(self.bot, interaction, bet, "crash"):
            return
        game = crash_game.CrashGame(bet, crash_game.crash_point(), time.monotonic(), auto_cashout)
        view = CrashView(self.bot, interaction, game)
        await self._start(interaction, view)
        while not game.finished:
            await asyncio.sleep(CRASH_TICK_SECONDS)
            game.tick(time.monotonic())
            if not game.finished:
                try:
                    await view.message.edit(embed=view.embed())
                except discord.HTTPException:
                    pass
        # The button handler already settled and redrew if the player cashed out by hand.
        unlocked = view.settle_if_done()
        if unlocked is not None:
            try:
                await view.message.edit(embed=view.embed(), view=view)
            except discord.HTTPException:
                pass
            await self.bot.award(interaction, unlocked)

    @app_commands.command(description="Reveal gems, dodge mines. Every safe tile raises your payout.",
                          extras={"manual_cleanup": True})
    @app_commands.describe(mines="How many mines to hide among the 20 tiles (more mines, bigger multipliers)")
    async def mines(
        self, interaction: discord.Interaction, bet: Bet, mines: app_commands.Range[int, 1, 15] = 3
    ) -> None:
        if not await start_guard(self.bot, interaction, "mines") or not await take_bet(self.bot, interaction, bet, "mines"):
            return
        await self._start(interaction, MinesView(self.bot, interaction, mines_game.MinesGame(bet, mines)))

    @app_commands.command(description="Guess if the next card is higher or lower. Keep going to grow your multiplier.",
                          extras={"manual_cleanup": True})
    async def highlow(self, interaction: discord.Interaction, bet: Bet) -> None:
        if not await start_guard(self.bot, interaction, "higher or lower") or not await take_bet(self.bot, interaction, bet, "higher or lower"):
            return
        await self._start(interaction, HighLowView(self.bot, interaction, highlow.HighLowGame(bet)))


async def setup(bot) -> None:
    await bot.add_cog(Arcade(bot))
