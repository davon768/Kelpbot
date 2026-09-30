"""Runs the real slash commands and buttons against fake Discord objects."""

import asyncio

from conftest import FIRST_WIN, GUILD, FakeInteraction, FakeMember, call, noop, press
from kelpbot import config, settings


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
    monkeypatch.setattr(asyncio, "sleep", lambda s: noop())  # skip the reel animation
    call(kb, "slots", FakeMember(1), bet=100)
    assert kb.db.account(GUILD, 1).games_played == 1


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
    monkeypatch.setattr(asyncio, "sleep", lambda s: noop())
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
