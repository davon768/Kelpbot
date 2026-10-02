"""/games: every game in one list, with a Play menu that opens a bet form and starts the game."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import discord
from discord import app_commands
from discord.ext import commands

from kelpbot import config
from kelpbot.games import dice, horses
from kelpbot.games import crash as crash_game


def parse_int(low: int, high: int | None = None) -> Callable[[str], int]:
    def parse(text: str) -> int:
        try:
            value = int(text.strip().replace(",", "").replace("_", ""))
        except ValueError:
            raise ValueError("needs to be a whole number") from None
        if value < low or (high is not None and value > high):
            raise ValueError(f"must be between {low:,} and {high:,}" if high is not None else f"must be at least {low:,}")
        return value
    return parse


def parse_side(text: str) -> str:
    side = text.strip().lower()
    if side in ("h", "heads"):
        return "heads"
    if side in ("t", "tails"):
        return "tails"
    raise ValueError("must be heads or tails")


def parse_cashout(text: str) -> float | None:
    text = text.strip().lower().rstrip("x")
    if not text:
        return None
    try:
        value = float(text)
    except ValueError:
        raise ValueError("needs to be a number like 2.5") from None
    if not 1.01 <= value <= crash_game.MAX_MULTIPLIER:
        raise ValueError(f"must be between 1.01 and {crash_game.MAX_MULTIPLIER:g}")
    return value


@dataclass(frozen=True)
class Field:
    param: str
    label: str
    placeholder: str
    parse: Callable[[str], object]
    required: bool = True
    default: str = ""


@dataclass(frozen=True)
class Game:
    key: str  # the name used by /settings game
    command: str  # slash command path, e.g. "lottery buy"
    emoji: str
    name: str
    blurb: str
    top_payout: str
    fields: tuple[Field, ...] = ()
    has_bet: bool = True
    playable: bool = True  # False: needs something a form can't ask for (like picking a member)


BET = Field("bet", "Bet", "", parse_int(1))
GAMES: tuple[Game, ...] = (
    Game("slots", "slots", "🎰", "Slots", "Three reels. Line up three of a kind.", "500x"),
    Game("blackjack", "blackjack", "🃏", "Blackjack", "Beat the dealer to 21 with Hit, Stand and Double.", "2.5x"),
    Game("coinflip", "coinflip", "🪙", "Coinflip", "Call heads or tails. Double or nothing.", "2x",
         (Field("side", "Heads or tails?", "heads", parse_side, default="heads"),)),
    Game("roulette", "roulette", "🎡", "Roulette", "Bet on a colour, odd/even, a dozen or one number.", "36x",
         (Field("choice", "Your bet", "red, black, odd, even, low, high, 1st12, 2nd12, 3rd12 or 0-36",
                lambda t: t.strip(), default="red"),)),
    Game("dice", "dice", "🎲", "Dice", "Pick your win chance. The rarer the roll, the bigger the payout.", "98x",
         (Field("chance", "Win chance (%)", "1-95 (50 pays 1.96x)", parse_int(dice.MIN_CHANCE, dice.MAX_CHANCE),
                default="50"),)),
    Game("crash", "crash", "🚀", "Crash", "Cash out before the multiplier crashes.", "100x",
         (Field("auto_cashout", "Auto cash-out (optional)", "e.g. 2.5, or leave empty", parse_cashout,
                required=False),)),
    Game("mines", "mines", "💣", "Mines", "Reveal gems and dodge the mines on a 20-tile board.", "1,000x+",
         (Field("mines", "How many mines?", "1-15 (more mines, bigger multipliers)", parse_int(1, 15), default="3"),)),
    Game("higher or lower", "highlow", "🔮", "Higher or Lower", "Guess the next card. Build a streak, then cash out.",
         "1,000x"),
    Game("horse race", "race", "🏇", "Horse Race", "Back a horse and watch the race live with everyone.", "11.8x",
         (Field("horse", "Horse number (1-5)",
                " · ".join(f"{h.number} {h.name.split()[0]} {h.payout}x" for h in horses.HORSES)[:100],
                parse_int(1, len(horses.HORSES)), default="1"),)),
    Game("heist", "heist", "💰", "Heist", "Start a heist. Friends join with the same buy-in.", "1.9x"),
    Game("lottery", "lottery buy", "🎟️", "Lottery", "Buy tickets for the server-wide jackpot.", "the pot",
         (Field("tickets", "How many tickets?", f"1-{config.LOTTERY_MAX_TICKETS}",
                parse_int(1, config.LOTTERY_MAX_TICKETS), default="1"),), has_bet=False),
    Game("trivia", "trivia", "🧠", "Trivia", "Answer a question before the timer runs out. Everyone can play.",
         "375 coins", has_bet=False),
    Game("duel", "duel", "⚔️", "Duel", "Challenge a player. Winner takes both bets. Use `/duel @player bet`.", "2x",
         playable=False),
)
BY_KEY = {g.key: g for g in GAMES}


class PlayModal(discord.ui.Modal):
    def __init__(self, cog: "GamesMenu", game: Game, cfg) -> None:
        super().__init__(title=f"Play {game.name}"[:45])
        self.cog = cog
        self.game = game
        self.inputs: dict[str, tuple[Field, discord.ui.TextInput]] = {}
        fields = ((BET,) if game.has_bet else ()) + game.fields
        for f in fields:
            placeholder = f.placeholder
            if f is BET:
                limit = f"{cfg.max_bet:,}" if cfg.max_bet else "no limit"
                placeholder = f"Between {cfg.min_bet:,} and {limit}"
            text = discord.ui.TextInput(label=f.label, placeholder=placeholder[:100], required=f.required,
                                        default=f.default or None, max_length=60)
            self.add_item(text)
            self.inputs[f.param] = (f, text)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        kwargs = {}
        for param, (field, text) in self.inputs.items():
            try:
                kwargs[param] = field.parse(text.value) if text.value.strip() or field.required else None
            except ValueError as exc:
                await interaction.response.send_message(f"❌ {field.label} {exc}.", ephemeral=True)
                return
        await self.cog.run(interaction, self.game, kwargs)


class GamePicker(discord.ui.View):
    def __init__(self, cog: "GamesMenu", user_id: int, games: list[Game]) -> None:
        super().__init__(timeout=300)
        self.cog = cog
        self.user_id = user_id
        self.select = discord.ui.Select(
            placeholder="▶ Pick a game to play",
            options=[discord.SelectOption(label=g.name, emoji=g.emoji, value=g.key,
                                          description=g.blurb[:100]) for g in games],
        )
        self.select.callback = self.pick
        self.add_item(self.select)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Run `/games` to get your own menu.", ephemeral=True)
            return False
        return True

    async def pick(self, interaction: discord.Interaction) -> None:
        game = BY_KEY[self.select.values[0]]
        if not game.has_bet and not game.fields:  # nothing to ask (trivia): start straight away
            await self.cog.run(interaction, game, {})
            return
        await interaction.response.send_modal(PlayModal(self.cog, game, self.cog.bot.cfg(interaction.guild_id)))


class GamesMenu(commands.Cog):
    def __init__(self, bot) -> None:
        self.bot = bot

    def find_command(self, path: str) -> app_commands.Command:
        first, *rest = path.split()
        command = self.bot.tree.get_command(first)
        for part in rest:
            command = command.get_command(part)
        return command

    async def run(self, interaction: discord.Interaction, game: Game, kwargs: dict) -> None:
        """Start a game exactly as if the player had typed its slash command."""
        command = self.find_command(game.command)
        await command.callback(command.binding, interaction, **kwargs)
        # Typed commands get auto-delete and channel tracking from the completion hook; do the same here.
        cleanup = self.bot.get_cog("Cleanup")
        if cleanup is not None:
            await cleanup.on_app_command_completion(interaction, command)

    @app_commands.command(description="Every game in one list. Pick one to play it.")
    async def games(self, interaction: discord.Interaction) -> None:
        cfg = self.bot.cfg(interaction.guild_id)
        lines, playable = [], []
        for g in GAMES:
            if g.key in cfg.disabled_games:
                lines.append(f"~~{g.emoji} {g.name}~~ · turned off in this server")
                continue
            lines.append(f"{g.emoji} **{g.name}** · up to {g.top_payout}\n-# {g.blurb}")
            if g.playable:
                playable.append(g)
        limit = cfg.money(cfg.max_bet) if cfg.max_bet else "no limit"
        embed = discord.Embed(
            title="🎮 Games",
            description="\n".join(lines) + f"\n\nBets: {cfg.money(cfg.min_bet)} to {limit}. "
                        "Pick a game below and enter your bet to start.",
            color=discord.Color.purple(),
        )
        view = GamePicker(self, interaction.user.id, playable) if playable else None
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


async def setup(bot) -> None:
    await bot.add_cog(GamesMenu(bot))
