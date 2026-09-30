"""End-to-end checks for jobs, quests, pets, events, heists, races, stocks, help and admin tools."""

import asyncio
import datetime as dt
from types import SimpleNamespace

import pytest

from conftest import GUILD, FakeInteraction, FakeMember, call, loaded, press
from kelpbot import config, jobs, server_events, settings
from kelpbot.cogs.help import CATEGORIES, UNLISTED


def test_work_levels_up_and_promotes(kb):
    alice = FakeMember(1)
    kb.db.add_work_xp(GUILD, 1, jobs.xp_for_level(3) - 1)  # one XP short of Fisher
    it = call(kb, "work", alice)
    assert "promoted to **🎣 Fisher**" in it.last_text
    assert any(e.kind == "promotion" for e in kb.db.recent_events(GUILD))
    assert "Fisher" in call(kb, "job", alice).last_text


def test_double_pay_and_xp_boost(kb, monkeypatch):
    import random
    monkeypatch.setattr(random, "randint", lambda a, b: a)
    server_events.start(kb.db, GUILD, "double_pay", 60)
    it = call(kb, "work", FakeMember(1))
    assert f"**{config.CURRENCY} {config.WORK_PAY[0] * 2}**" in it.last_text and "double pay" in it.last_text
    server_events.start(kb.db, GUILD, "xp_boost", 60)
    call(kb, "work", FakeMember(2))
    assert kb.db.account(GUILD, 2).work_xp == config.WORK_XP[0] * 2


def test_octopus_shortens_work_cooldown(kb):
    alice = FakeMember(1)
    kb.db.add_item(GUILD, 1, "octopus")
    call(kb, "work", alice)
    assert "45m" in call(kb, "work", alice).last_text


def test_new_accounts_cant_give_or_be_robbed(kb):
    fresh = FakeMember(3, created_at=dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=1))
    it = call(kb, "give", fresh, user=FakeMember(1), amount=10)
    assert "can't send money yet" in it.last_text and kb.db.balance(GUILD, 3) == 1000
    it = call(kb, "rob", FakeMember(1), user=fresh)
    assert "too new to rob" in it.last_text


def test_disabled_game_takes_no_money(kb):
    call(kb, "settings game", FakeMember(9), game="slots", enabled=False)
    it = call(kb, "slots", FakeMember(1), bet=100)
    assert "turned off" in it.last_text and kb.db.balance(GUILD, 1) == 1000
    assert "slots" in call(kb, "settings view", FakeMember(9)).last_text


def test_unfinished_game_is_refunded_after_restart(kb):
    alice = FakeMember(1)
    view = call(kb, "blackjack", alice, bet=300).sent[-1].view
    if view.settled:
        pytest.skip("dealt a natural blackjack, nothing left open")
    assert kb.db.balance(GUILD, 1) == 700
    # simulate the bot restarting: the view is gone, the stored stake comes back
    assert kb.db.refund_open_bets() == [(GUILD, 1, "blackjack", 300)]
    assert kb.db.balance(GUILD, 1) == 1000


def test_finished_games_leave_nothing_open(kb):
    alice = FakeMember(1)
    view = call(kb, "mines", alice, bet=100, mines=1).sent[-1].view
    press(kb, view, view.tiles[next(iter(view.game.mine_tiles))], alice)
    assert kb.db.open_bets() == []


def run_with(kb, coro_fn):
    return kb.run(coro_fn())


def test_heist_with_crew(kb, monkeypatch):
    monkeypatch.setattr(config, "HEIST_LOBBY_SECONDS", 5)
    monkeypatch.setattr(loaded("kelpbot.cogs.heist"), "STEP_SECONDS", 0)
    alice, bob = FakeMember(1, "Alice"), FakeMember(2, "Bob")

    async def play():
        it = FakeInteraction(alice)
        cmd = kb.tree.get_command("heist")
        task = asyncio.ensure_future(cmd.callback(cmd.binding, it, bet=200))
        while not it.sent:
            await asyncio.sleep(0)
        view = it.sent[-1].view
        await view.join.callback(FakeInteraction(bob))
        assert "only the heist leader" in (await _press(view, view.start, bob)).lower()
        await view.start.callback(FakeInteraction(alice))
        await task
        return view

    view = run_with(kb, play)
    assert len(view.crew) == 2 and kb.db.open_bets() == []
    a, b = kb.db.balance(GUILD, 1), kb.db.balance(GUILD, 2)
    assert (a, b) == (800, 800) or (a >= 1000 + 180 and b >= 1000 + 180)
    assert any(e.kind == "heist" for e in kb.db.recent_events(GUILD))


async def _press(view, item, who):
    it = FakeInteraction(who)
    await item.callback(it)
    return it.last_text


def test_solo_heist_is_refunded(kb, monkeypatch):
    monkeypatch.setattr(config, "HEIST_LOBBY_SECONDS", 0.01)
    it = call(kb, "heist", FakeMember(1), bet=200)
    assert kb.db.balance(GUILD, 1) == 1000 and kb.db.open_bets() == []
    assert "called off" in it.message.edits[-1]["embed"].title


class RaceChannel:
    def __init__(self):
        self.edits = []

    def get_partial_message(self, mid):
        async def edit(embed=None, **kw):
            self.edits.append(embed)
        return SimpleNamespace(edit=edit)


def test_horse_race_with_two_bettors(kb, monkeypatch):
    monkeypatch.setattr(config, "RACE_BETTING_SECONDS", 0.05)
    monkeypatch.setattr(loaded("kelpbot.cogs.race"), "FRAME_SECONDS", 0)
    channel = RaceChannel()
    kb.get_partial_messageable = lambda cid: channel
    alice, bob = FakeMember(1, "Alice"), FakeMember(2, "Bob")

    async def play():
        it = FakeInteraction(alice)
        cmd = kb.tree.get_command("race")
        task = asyncio.ensure_future(cmd.callback(cmd.binding, it, horse=1, bet=100))
        while not it.sent:
            await asyncio.sleep(0)
        second = FakeInteraction(bob)
        await cmd.callback(cmd.binding, second, horse=5, bet=100)
        again = FakeInteraction(bob)
        await cmd.callback(cmd.binding, again, horse=2, bet=100)
        await task
        return second, again

    second, again = run_with(kb, play)
    assert second.sent[-1].ephemeral and "already have a bet" in again.last_text
    final = channel.edits[-1]
    assert "wins!" in final.title
    winner = int(final.description.split("`")[1])
    paid = {1: int(100 * 2.7), 5: int(100 * 11.8)}
    for uid, horse in ((1, 1), (2, 5)):
        bal = kb.db.balance(GUILD, uid)
        assert bal == 900 or (horse == winner and bal >= 900 + paid[horse])
    assert kb.db.open_bets() == []


def test_stock_commands(kb):
    alice = FakeMember(1)
    assert "KELP" in call(kb, "stocks market", alice).last_text
    call(kb, "stocks buy", alice, stock="KELP", shares=5)
    assert kb.db.holdings(GUILD, 1)["KELP"][0] == 5
    assert "KELP" in call(kb, "stocks portfolio", alice).last_text
    assert "only own 5" in call(kb, "stocks sell", alice, stock="KELP", shares=6).last_text
    call(kb, "stocks sell", alice, stock="KELP", shares=5)
    assert kb.db.holdings(GUILD, 1) == {}
    settings.set_game_enabled(kb.db, GUILD, "stocks", False)
    assert "turned off" in call(kb, "stocks market", alice).last_text


def test_profile_and_quests(kb):
    alice = FakeMember(1)
    kb.db.log_game(GUILD, 1, "crash", 100, 300)
    kb.db.add_item(GUILD, 1, "cat")
    body = call(kb, "profile", alice).last_text
    assert "Kelp Farmer" in body and "crash (1 games)" in body and "🐱" in body
    assert "Daily quests" in call(kb, "quests", alice).last_text


def test_buying_every_pet_unlocks_zookeeper(kb):
    alice = FakeMember(1)
    kb.db.credit(GUILD, 1, 1_000_000)
    for pet in ("cat", "parrot", "dog", "turtle", "octopus"):
        call(kb, "buy", alice, item=pet)
    it = call(kb, "buy", alice, item="dragon")
    assert "Zookeeper" in it.followups[-1].embed.description


def test_help_lists_every_command(kb):
    listed = {name for names in CATEGORIES.values() for name in names}
    registered = {c.name for c in kb.tree.get_commands()}
    assert registered - UNLISTED == listed, "every command needs a /help category"
    it = call(kb, "help", FakeMember(1))
    view = it.sent[-1].view
    assert it.sent[-1].ephemeral and len(view.select.options) == len(CATEGORIES)
    it.permissions = SimpleNamespace(manage_guild=False)
    member = FakeInteraction(FakeMember(2))
    member.permissions = SimpleNamespace(manage_guild=False)
    cmd = kb.tree.get_command("help")
    kb.run(cmd.callback(cmd.binding, member))
    assert len(member.sent[-1].view.select.options) == len(CATEGORIES) - 1  # no admin section


def test_event_commands(kb):
    announced = []

    async def fake_announce(gid, embed, fallback_channel_id=0):
        announced.append(embed.title)

    kb.announce = fake_announce
    admin = FakeMember(9)
    call(kb, "event start", admin, event="lucky_hour", minutes=30)
    assert server_events.is_active(kb.db, GUILD, "lucky_hour") and "Lucky Hour has started!" in announced[-1]
    call(kb, "event stop", admin)
    assert server_events.active(kb.db, GUILD) is None
    assert "No event" in call(kb, "event stop", admin).last_text


def test_backup_is_owner_only(kb):
    async def not_owner(user):
        return False

    kb.is_owner = not_owner
    assert "Only the bot's owner" in call(kb, "backup", FakeMember(9)).last_text

    async def owner(user):
        return True

    kb.is_owner = owner
    it = call(kb, "backup", FakeMember(9))
    assert it.followups[-1].file is not None
