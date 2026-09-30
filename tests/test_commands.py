"""Runs the real slash commands and buttons against fake Discord objects."""

import asyncio
import itertools
from types import SimpleNamespace

import pytest

import bot as bot_module
from kelpbot import config, settings

GUILD = 1
_ids = itertools.count(1000)


class FakeMessage:
    def __init__(self, channel_id=50, ephemeral=False):
        self.id = next(_ids)
        self.channel = SimpleNamespace(id=channel_id)
        self.flags = SimpleNamespace(ephemeral=ephemeral)
        self.edits = []

    async def edit(self, **kw):
        self.edits.append(kw)


class FakeMember:
    def __init__(self, uid, name="player"):
        self.id = uid
        self.display_name = name
        self.mention = f"<@{uid}>"
        self.bot = False
        self.roles = []
        self.display_avatar = SimpleNamespace(url="https://example.invalid/a.png")

    async def add_roles(self, role, reason=None):
        self.roles.append(role)


class FakeResponse:
    def __init__(self, it):
        self.it, self.done = it, False

    def is_done(self):
        return self.done

    async def send_message(self, content=None, *, embed=None, view=None, ephemeral=False, **kw):
        self.done = True
        self.it.sent.append(SimpleNamespace(content=content, embed=embed, view=view, ephemeral=ephemeral))
        self.it.message = FakeMessage(ephemeral=ephemeral)

    async def edit_message(self, *, embed=None, view=None, **kw):
        self.done = True
        self.it.edits.append(SimpleNamespace(embed=embed, view=view))

    async def defer(self, **kw):
        self.done = True


class FakeFollowup:
    def __init__(self, it):
        self.it = it

    async def send(self, content=None, *, embed=None, wait=False, **kw):
        self.it.followups.append(SimpleNamespace(content=content, embed=embed))
        return FakeMessage()


class FakeInteraction:
    def __init__(self, user, guild_id=GUILD):
        self.user = user
        self.guild_id = guild_id
        self.channel_id = 50
        self.guild = SimpleNamespace(me=SimpleNamespace(guild_permissions=SimpleNamespace(manage_roles=True)))
        self.response = FakeResponse(self)
        self.followup = FakeFollowup(self)
        self.sent, self.edits, self.followups = [], [], []
        self.message = None

    async def original_response(self):
        return self.message

    async def edit_original_response(self, **kw):
        self.edits.append(SimpleNamespace(**{"embed": None, "view": None, **kw}))

    @property
    def last_text(self):
        last = (self.edits or self.sent)[-1]
        embed = getattr(last, "embed", None)
        parts = [getattr(last, "content", None) or ""]
        if embed:
            parts += [embed.title or "", embed.description or ""] + [f"{f.name} {f.value}" for f in embed.fields]
        return "\n".join(parts)


@pytest.fixture
def kb(monkeypatch):
    monkeypatch.setattr(config, "DATABASE_PATH", ":memory:")
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    b = bot_module.KelpBot()
    b.db.auto_delete_default = 0  # no background deletes in tests
    b.wait_until_ready = lambda: asyncio.sleep(3600)
    for ext in bot_module.EXTENSIONS:
        loop.run_until_complete(b.load_extension(ext))
    b.lock_commands_to_servers()
    b.run = loop.run_until_complete
    yield b
    for task in asyncio.all_tasks(loop):
        task.cancel()
    loop.run_until_complete(asyncio.sleep(0))
    loop.close()


def call(kb, name, who, **kwargs):
    """Invoke a slash command as `who` (use 'group sub' for subcommands)."""
    parts = name.split()
    cmd = kb.tree.get_command(parts[0])
    for part in parts[1:]:
        cmd = cmd.get_command(part)
    it = FakeInteraction(who)
    binding = cmd.binding
    kb.run(cmd.callback(binding, it, **kwargs))
    return it


def press(kb, view, item, who):
    """Click a button the way Discord does: the view's interaction_check runs first."""
    it = FakeInteraction(who)

    async def click():
        if await view.interaction_check(it):
            await item.callback(it)

    kb.run(click())
    return it


FIRST_WIN = 250  # "Beginner's Luck" achievement reward, paid on a player's first win


def test_balance_daily_work_deposit_withdraw(kb):
    alice = FakeMember(1, "Alice")
    assert "1,000" in call(kb, "balance", alice).last_text
    assert "claimed" in call(kb, "daily", alice).last_text
    assert "earned" in call(kb, "work", alice).last_text
    assert "can `/work` again" in call(kb, "work", alice).last_text
    wallet = kb.db.balance(GUILD, 1)
    call(kb, "deposit", alice, amount="half")
    acct = kb.db.account(GUILD, 1)
    assert acct.bank == wallet // 2 and acct.balance == wallet - wallet // 2
    call(kb, "withdraw", alice, amount="all")
    assert kb.db.account(GUILD, 1).bank == 0


def test_bet_limits_come_from_server_settings(kb):
    alice = FakeMember(1)
    settings.save(kb.db, GUILD, "max_bet", 100)
    it = call(kb, "coinflip", alice, bet=500, side="heads")
    assert it.sent[-1].ephemeral and "maximum bet" in it.last_text
    assert kb.db.balance(GUILD, 1) == 1000
    it = call(kb, "coinflip", alice, bet=5, side="heads")
    assert "minimum bet" in it.last_text
    call(kb, "coinflip", alice, bet=100, side="heads")
    assert kb.db.balance(GUILD, 1) in (900, 1100 + FIRST_WIN)


def test_currency_setting_shows_everywhere(kb):
    settings.save(kb.db, GUILD, "currency_emoji", "🐚")
    assert "🐚 1,000" in call(kb, "balance", FakeMember(1)).last_text


def test_rob_can_be_disabled(kb):
    settings.save(kb.db, GUILD, "rob_enabled", False)
    it = call(kb, "rob", FakeMember(1), user=FakeMember(2))
    assert "turned off" in it.last_text


def test_quick_games_run(kb):
    alice = FakeMember(1)
    kb.db.credit(GUILD, 1, 100_000)
    for name, kwargs in [
        ("coinflip", {"side": "tails"}),
        ("roulette", {"choice": "red"}),
        ("dice", {"chance": 50}),
    ]:
        call(kb, name, alice, bet=100, **kwargs)
    assert kb.db.account(GUILD, 1).games_played == 3


def test_slots_runs(kb, monkeypatch):
    monkeypatch.setattr(asyncio, "sleep", lambda s: _noop())  # skip the reel animation
    call(kb, "slots", FakeMember(1), bet=100)
    assert kb.db.account(GUILD, 1).games_played == 1


async def _noop():
    return None


def test_blackjack_buttons(kb):
    alice = FakeMember(1)
    it = call(kb, "blackjack", alice, bet=100)
    view = it.sent[-1].view
    if not view.settled:
        assert "isn't your game" in press(kb, view, view.hit, FakeMember(2)).last_text
        press(kb, view, view.stand, alice)
    assert view.settled and (GUILD, 1, "blackjack") not in kb.active_games
    assert kb.db.account(GUILD, 1).games_played == 1


def test_mines_flow(kb):
    alice = FakeMember(1)
    it = call(kb, "mines", alice, bet=100, mines=1)
    view = it.sent[-1].view
    safe = next(i for i in range(20) if i not in view.game.mine_tiles)
    press(kb, view, view.tiles[safe], alice)
    assert view.game.revealed == {safe}
    assert "isn't your game" in press(kb, view, view.cash, FakeMember(2)).last_text
    press(kb, view, view.cash, alice)
    assert view.settled
    assert kb.db.balance(GUILD, 1) == 1000 - 100 + int(100 * view.game.current_multiplier) + FIRST_WIN


def test_highlow_flow(kb):
    alice = FakeMember(1)
    it = call(kb, "highlow", alice, bet=100)
    view = it.sent[-1].view
    higher = view.game.card <= 7
    press(kb, view, view.higher if higher else view.lower, alice)
    if not view.game.lost:
        press(kb, view, view.cash, alice)
    assert view.settled


def test_crash_manual_cash_out(kb, monkeypatch):
    from kelpbot.cogs import arcade
    monkeypatch.setattr(arcade, "CRASH_TICK_SECONDS", 0.01)
    monkeypatch.setattr(arcade.crash_game, "crash_point", lambda: 50.0)
    alice = FakeMember(1)

    async def play():
        it = FakeInteraction(alice)
        cmd = kb.tree.get_command("crash")
        task = asyncio.create_task(cmd.callback(cmd.binding, it, bet=100, auto_cashout=None))
        while not it.sent:
            await asyncio.sleep(0.001)
        view = it.sent[-1].view
        await view.cash.callback(FakeInteraction(alice))
        await task
        return view

    view = kb.run(play())
    assert view.game.cashed_out and view.settled
    bonus = FIRST_WIN if view.game.payout() > 100 else 0
    assert kb.db.balance(GUILD, 1) == 900 + view.game.payout() + bonus


def test_crash_auto_cash_out(kb, monkeypatch):
    from kelpbot.cogs import arcade
    monkeypatch.setattr(arcade, "CRASH_TICK_SECONDS", 0.01)
    monkeypatch.setattr(arcade.crash_game, "crash_point", lambda: 50.0)
    monkeypatch.setattr(arcade.crash_game, "GROWTH_PER_SECOND", 50.0)  # reach 2x almost instantly
    call(kb, "crash", FakeMember(1), bet=100, auto_cashout=2.0)
    assert kb.db.balance(GUILD, 1) == 1100 + FIRST_WIN


def test_duel_accept(kb, monkeypatch):
    monkeypatch.setattr(asyncio, "sleep", lambda s: _noop())
    alice, bob = FakeMember(1, "Alice"), FakeMember(2, "Bob")
    it = call(kb, "duel", alice, opponent=bob, bet=200)
    view = it.sent[-1].view
    assert kb.db.balance(GUILD, 1) == 800  # held in escrow
    assert "isn't for you" in press(kb, view, view.accept, FakeMember(3)).last_text
    press(kb, view, view.accept, bob)
    balances = sorted([kb.db.balance(GUILD, 1), kb.db.balance(GUILD, 2)])
    assert balances[0] == 800 and balances[1] >= 1200  # winner may also get achievement rewards


def test_duel_decline_refunds(kb):
    alice, bob = FakeMember(1), FakeMember(2)
    view = call(kb, "duel", alice, opponent=bob, bet=200).sent[-1].view
    press(kb, view, view.decline, bob)
    assert kb.db.balance(GUILD, 1) == 1000 and (GUILD, 1, "duel") not in kb.active_games


def test_lottery_commands(kb):
    alice = FakeMember(1)
    assert "No round running" in call(kb, "lottery info", alice).last_text
    call(kb, "lottery buy", alice, tickets=3)
    assert kb.db.balance(GUILD, 1) == 700
    assert "3 (100.0% chance)" in call(kb, "lottery info", alice).last_text


def test_lottery_draw_via_scheduler(kb):
    alice = FakeMember(1)
    call(kb, "lottery buy", alice, tickets=2)
    announced = []

    async def fake_announce(gid, embed, fallback_channel_id=0):
        announced.append(embed.description)

    kb.announce = fake_announce
    kb.run(kb.get_cog("Scheduler").draw_lottery(GUILD))
    assert announced and "<@1> won" in announced[0]
    assert kb.db.lottery_round(GUILD) is None


def test_settings_commands(kb):
    admin = FakeMember(9)
    it = call(kb, "settings set", admin, setting="max_bet", value="nope")
    assert "whole number" in it.last_text
    call(kb, "settings set", admin, setting="min_bet", value="500")
    it = call(kb, "settings set", admin, setting="max_bet", value="100")
    assert "can't be above" in it.last_text
    call(kb, "settings set", admin, setting="currency_name", value="Shells")
    assert "Shells" in call(kb, "settings view", admin).last_text
    call(kb, "settings reset", admin, setting="min_bet")
    assert kb.cfg(GUILD).min_bet == config.MIN_BET


def test_shop_items_and_achievement_progress(kb):
    alice = FakeMember(1)
    kb.db.credit(GUILD, 1, 10_000)
    it = call(kb, "buy", alice, item="energy_drink", quantity=10)
    assert "Shopaholic" in it.followups[-1].embed.description
    assert "Energy Drink" in call(kb, "inventory", alice).last_text


def test_leaderboards_and_info_commands(kb):
    alice = FakeMember(1)
    kb.db.record_game(GUILD, 1, 100, 300)
    assert "<@1>" in call(kb, "leaderboard", alice, board="weekly").last_text
    assert "<@1>" in call(kb, "leaderboard", alice, board="wealth").last_text
    assert "achievements" in call(kb, "achievements", alice).last_text
    assert "No seasons" in call(kb, "halloffame", alice).last_text
    assert call(kb, "paytable", alice).sent[-1].ephemeral
    assert "Games played" in call(kb, "stats", alice).last_text
