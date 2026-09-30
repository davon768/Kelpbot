"""Quick games: slots, blackjack, coinflip, roulette and dice."""

from __future__ import annotations

import asyncio
import random
from typing import Literal

import discord
from discord import app_commands
from discord.ext import commands

from kelpbot import achievements
from kelpbot.gambling import PlayerView, result_line, settle, start_guard, take_bet
from kelpbot.games import dice as dice_game
from kelpbot.games import roulette as roulette_game
from kelpbot.games import slots as slot_machine
from kelpbot.games.blackjack import BlackjackGame, format_hand, hand_value, is_blackjack
from kelpbot.games.horses import HORSES

Bet = app_commands.Range[int, 1]


class BlackjackView(PlayerView):
    game_name = "blackjack"

    def __init__(self, bot, interaction: discord.Interaction, game: BlackjackGame) -> None:
        super().__init__(bot, interaction)
        self.game = game
        self.unlocked: list = []
        if is_blackjack(game.player):
            self.unlocked += achievements.unlock(bot.db, self.guild_id, self.player.id, "natural")
        self._sync_buttons()

    def _sync_buttons(self) -> None:
        self.double.disabled = not self.game.can_double

    def embed(self) -> discord.Embed:
        g = self.game
        done = g.finished
        if done:
            text, color = result_line(self.cfg, g.bet, g.payout())
            title = f"🃏 Blackjack: {g.outcome.value}"
        else:
            text, color, title = "Hit, stand, or double down?", discord.Color.dark_green(), "🃏 Blackjack"
        dealer_value = hand_value(g.dealer) if done else "?"
        e = discord.Embed(title=title, description=text, color=color)
        e.add_field(name=f"Dealer ({dealer_value})", value=format_hand(g.dealer, hide_hole=not done), inline=False)
        e.add_field(name=f"{self.player.display_name} ({hand_value(g.player)})", value=format_hand(g.player), inline=False)
        footer = f"Bet: {g.bet:,}" + (" (doubled)" if g.doubled else "")
        if done:
            footer += f" • Wallet: {self.balance:,}"
        e.set_footer(text=footer)
        return e

    def finish_if_done(self) -> None:
        if self.game.finished:
            self.unlocked += self.finalize(self.game.bet, self.game.payout()) or []
        else:
            self._sync_buttons()

    async def _update(self, interaction: discord.Interaction) -> None:
        self.finish_if_done()
        await interaction.response.edit_message(embed=self.embed(), view=self)
        if self.settled:
            await self.bot.award(interaction, self.unlocked)
            self.unlocked = []

    @discord.ui.button(label="Hit", style=discord.ButtonStyle.primary, emoji="➕")
    async def hit(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        self.game.hit()
        await self._update(interaction)

    @discord.ui.button(label="Stand", style=discord.ButtonStyle.secondary, emoji="✋")
    async def stand(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        self.game.stand()
        await self._update(interaction)

    @discord.ui.button(label="Double", style=discord.ButtonStyle.success, emoji="⏫")
    async def double(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if not self.game.can_double:
            await interaction.response.send_message("You can only double on your first two cards.", ephemeral=True)
            return
        if not self.bot.db.try_debit(self.guild_id, self.player.id, self.game.bet):
            await interaction.response.send_message("You can't afford to double down.", ephemeral=True)
            return
        self.game.double_down()
        self.track_bet(self.game.bet)
        await self._update(interaction)

    async def on_timeout(self) -> None:
        # Player walked away: stand on whatever they have so the bet is resolved.
        if not self.game.finished:
            self.game.stand()
            self.finish_if_done()
            if self.message:
                try:
                    await self.message.edit(embed=self.embed(), view=self)
                except discord.HTTPException:
                    pass


class Casino(commands.Cog):
    def __init__(self, bot) -> None:
        self.bot = bot

    def _footer(self, bet: int, balance: int, extra: str = "") -> str:
        return f"{extra + ' • ' if extra else ''}Bet: {bet:,} • Wallet: {balance:,}"

    @app_commands.command(description="Spin the slot machine.")
    async def slots(self, interaction: discord.Interaction, bet: Bet) -> None:
        if not await take_bet(self.bot, interaction, bet, "slots"):
            return
        gid, uid = interaction.guild_id, interaction.user.id
        cfg = self.bot.cfg(gid)
        reels = slot_machine.spin()
        returned = bet * slot_machine.payout_multiplier(reels)
        balance, unlocked = settle(self.bot, gid, uid, bet, returned, "slots")
        if all(s == slot_machine.SYMBOLS[-1] for s in reels):
            unlocked += achievements.unlock(self.bot.db, gid, uid, "jackpot")

        # Little spinning animation, revealing one reel at a time.
        embed = discord.Embed(title="🎰 Slots", description="**[ ❓ | ❓ | ❓ ]**", color=discord.Color.purple())
        await interaction.response.send_message(embed=embed)
        for i in range(1, len(reels) + 1):
            await asyncio.sleep(0.7)
            shown = [s.emoji for s in reels[:i]] + ["❓"] * (len(reels) - i)
            embed.description = f"**[ {' | '.join(shown)} ]**"
            await interaction.edit_original_response(embed=embed)

        text, embed.color = result_line(cfg, bet, returned)
        embed.description += f"\n\n{text}"
        embed.set_footer(text=self._footer(bet, balance))
        await interaction.edit_original_response(embed=embed)
        await self.bot.award(interaction, unlocked)

    # Cleaned up by BlackjackView when the hand ends, not when the command returns.
    @app_commands.command(description="Play a hand of blackjack against the dealer.", extras={"manual_cleanup": True})
    async def blackjack(self, interaction: discord.Interaction, bet: Bet) -> None:
        if not await start_guard(self.bot, interaction, "blackjack") or not await take_bet(self.bot, interaction, bet, "blackjack"):
            return
        view = BlackjackView(self.bot, interaction, BlackjackGame(bet=bet))
        self.bot.active_games.add(view.key)
        view.track_bet(bet)
        view.finish_if_done()  # natural blackjacks settle immediately
        await interaction.response.send_message(embed=view.embed(), view=view)
        view.message = await interaction.original_response()
        if view.settled:  # natural blackjack finished before the message existed
            self.bot.schedule_cleanup(interaction.guild_id, view.message.channel.id, view.message.id)
        await self.bot.award(interaction, view.unlocked)
        view.unlocked = []

    @app_commands.command(description="Flip a coin. Double or nothing.")
    async def coinflip(self, interaction: discord.Interaction, bet: Bet, side: Literal["heads", "tails"]) -> None:
        if not await take_bet(self.bot, interaction, bet, "coinflip"):
            return
        cfg = self.bot.cfg(interaction.guild_id)
        result = random.choice(["heads", "tails"])
        returned = bet * 2 if result == side else 0
        balance, unlocked = settle(self.bot, interaction.guild_id, interaction.user.id, bet, returned, "coinflip")
        text, color = result_line(cfg, bet, returned)
        embed = discord.Embed(title="🪙 Coinflip", description=f"It landed on **{result}**!\n\n{text}", color=color)
        embed.set_footer(text=self._footer(bet, balance, f"You picked {side}"))
        await interaction.response.send_message(embed=embed)
        await self.bot.award(interaction, unlocked)

    @app_commands.command(description="Bet on roulette: red/black, odd/even, low/high, 1st12/2nd12/3rd12, or a number 0-36.")
    @app_commands.describe(choice="red, black, odd, even, low, high, 1st12, 2nd12, 3rd12, or a number 0-36")
    async def roulette(self, interaction: discord.Interaction, bet: Bet, choice: str) -> None:
        parsed = roulette_game.parse_choice(choice)
        if parsed is None:
            await interaction.response.send_message(
                "Invalid choice. Use red, black, odd, even, low, high, 1st12, 2nd12, 3rd12 or a number 0-36.",
                ephemeral=True,
            )
            return
        if not await take_bet(self.bot, interaction, bet, "roulette"):
            return
        cfg = self.bot.cfg(interaction.guild_id)
        n = roulette_game.spin()
        returned = bet * roulette_game.payout_multiplier(parsed, n)
        balance, unlocked = settle(self.bot, interaction.guild_id, interaction.user.id, bet, returned, "roulette")
        text, color = result_line(cfg, bet, returned)
        embed = discord.Embed(
            title="🎡 Roulette",
            description=f"The ball landed on {roulette_game.color_emoji(n)} **{n}**\n\n{text}",
            color=color,
        )
        embed.set_footer(text=self._footer(bet, balance, f"You bet on {parsed}"))
        await interaction.response.send_message(embed=embed)
        await self.bot.award(interaction, unlocked)

    @roulette.autocomplete("choice")
    async def _roulette_choices(self, _: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        options = list(roulette_game.OUTSIDE_BETS) + ["0", "7", "17", "36"]
        return [app_commands.Choice(name=o, value=o) for o in options if current.lower() in o][:25]

    @app_commands.command(description="Roll 1-100. Win if you roll at or under your win chance. Lower chance, bigger payout.")
    @app_commands.describe(chance="Your chance to win, in percent (1-95). 50 pays 1.96x, 10 pays 9.8x.")
    async def dice(
        self,
        interaction: discord.Interaction,
        bet: Bet,
        chance: app_commands.Range[int, dice_game.MIN_CHANCE, dice_game.MAX_CHANCE] = 50,
    ) -> None:
        if not await take_bet(self.bot, interaction, bet, "dice"):
            return
        cfg = self.bot.cfg(interaction.guild_id)
        rolled = dice_game.roll()
        returned = dice_game.payout(bet, chance, rolled)
        balance, unlocked = settle(self.bot, interaction.guild_id, interaction.user.id, bet, returned, "dice")
        text, color = result_line(cfg, bet, returned)
        verdict = "✅" if rolled <= chance else "❌"
        embed = discord.Embed(
            title="🎲 Dice",
            description=f"You needed **{chance} or under** ({dice_game.multiplier(chance)}x).\n"
            f"Rolled **{rolled}** {verdict}\n\n{text}",
            color=color,
        )
        embed.set_footer(text=self._footer(bet, balance))
        await interaction.response.send_message(embed=embed)
        await self.bot.award(interaction, unlocked)

    @app_commands.command(description="How each game pays out.")
    async def paytable(self, interaction: discord.Interaction) -> None:
        cfg = self.bot.cfg(interaction.guild_id)
        e = discord.Embed(title="💰 Payouts", color=discord.Color.gold())
        e.add_field(name="🎰 Slots", value="\n".join(slot_machine.paytable_lines()), inline=False)
        e.add_field(
            name="🃏 Blackjack",
            value="Win → **2x** • Blackjack → **2.5x** • Push → bet back\n"
            "Dealer stands on 17. Double down on your first two cards.",
            inline=False,
        )
        e.add_field(name="🪙 Coinflip", value="Correct call → **2x**", inline=False)
        e.add_field(
            name="🎡 Roulette",
            value="Red/black, odd/even, low/high → **2x**\nDozens (1st12/2nd12/3rd12) → **3x**\nSingle number → **36x**",
            inline=False,
        )
        e.add_field(name="🎲 Dice", value="Pick a win chance from 1-95%. Payout ≈ 98 ÷ chance (50% → 1.96x).", inline=False)
        e.add_field(
            name="🚀 Crash • 💣 Mines • 🔮 Higher or Lower",
            value="Multipliers grow as you go. Cash out before you lose it all!",
            inline=False,
        )
        e.add_field(name="⚔️ Duel", value="50/50 against another player. Winner takes both bets.", inline=False)
        e.add_field(name="💰 Heist", value="Crew of 2: 50% for 1.9x · 3: 60% for 1.58x · 4: 70% for 1.35x · "
                                           "5+: 80% for 1.18x", inline=False)
        e.add_field(name="🏇 Horse race", value=" · ".join(f"{h.name} {h.payout}x" for h in HORSES), inline=False)
        max_text = f"{cfg.max_bet:,} maximum" if cfg.max_bet else "no maximum"
        e.set_footer(text=f"Bets: {cfg.min_bet:,} minimum, {max_text}. Payouts include your original bet.")
        await interaction.response.send_message(embed=e, ephemeral=True)


async def setup(bot) -> None:
    await bot.add_cog(Casino(bot))
