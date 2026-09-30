"""Rules for restart refunds, backups, jobs, quests, pets, events, stocks, heists, races and alt checks."""

import datetime as dt
import os
import random
from types import SimpleNamespace

import pytest

from kelpbot import backup, bank, config, jobs, perks, quests, server_events, settings, stocks, tracker
from kelpbot.db import Database
from kelpbot.gambling import settle
from kelpbot.games import heist, horses
from kelpbot.robbery import attempt_rob
from kelpbot.trust import trust_problem

G, U = 1, 42
NOW = 1_790_000_000.0


def make(balance=1000):
    return Database(":memory:", starting_balance=balance)


def fake_bot(db):
    return SimpleNamespace(db=db, cfg=lambda gid: settings.load(db, gid), log_event=lambda *a: None)


# ---- restart refunds ------------------------------------------------------------------

def test_open_bets_are_refunded_once():
    db = make()
    db.try_debit(G, U, 300)
    bet_id = db.open_bet(G, U, "blackjack", 300)
    db.update_open_bet(bet_id, 600)  # doubled down
    db.try_debit(G, U, 300)
    finished = db.open_bet(G, U, "crash", 100)
    db.close_bet(finished)
    assert db.refund_open_bets() == [(G, U, "blackjack", 600)]
    assert db.balance(G, U) == 1000 and db.refund_open_bets() == []


# ---- backups ---------------------------------------------------------------------------

def test_daily_backup(tmp_path):
    path = str(tmp_path / "kelpbot.db")
    db = Database(path, 1000)
    db.credit(G, U, 5)
    first = backup.daily_backup(db, path, NOW)
    assert first and os.path.exists(first)
    assert Database(first, 0).balance(G, U) == 1005  # a real, readable copy
    assert backup.daily_backup(db, path, NOW + 60) is None  # once per day
    for day in range(1, 10):
        backup.daily_backup(db, path, NOW + day * 86400)
    assert len(os.listdir(backup.backup_dir(path))) == config.BACKUP_KEEP_DAYS
    assert backup.daily_backup(make(), ":memory:", NOW) is None


# ---- jobs --------------------------------------------------------------------------------

def test_levels_and_jobs():
    assert jobs.level_for(0) == 1 and jobs.level_for(49) == 1 and jobs.level_for(50) == 2
    assert jobs.job_for(1).name == "Kelp Farmer" and jobs.job_for(4).name == "Fisher"
    assert jobs.job_for(99) == jobs.TOP_JOB and jobs.next_job(25) is None
    assert jobs.next_job(1).name == "Fisher"
    assert jobs.progress_bar(25) == "▰▰▰▰▰▱▱▱▱▱"
    multipliers = [j.multiplier for j in jobs.JOBS]
    assert multipliers == sorted(multipliers)


# ---- quests -------------------------------------------------------------------------------

def test_quests_are_stable_per_day_and_differ_between_days():
    a = quests.todays_quests(G, U, "20260930")
    assert a == quests.todays_quests(G, U, "20260930") and len(a) == config.QUESTS_PER_DAY
    days = {tuple(q.key for q in quests.todays_quests(G, U, f"202610{d:02d}")) for d in range(1, 15)}
    assert len(days) > 5


def force_quests(monkeypatch, keys):
    monkeypatch.setattr(quests, "todays_quests", lambda g, u, d: [quests.QUESTS[k] for k in keys])


def test_quest_progress_pays_once_plus_bonus(monkeypatch):
    force_quests(monkeypatch, ["work_2", "rob_1", "lottery_3"])
    db = make()
    assert quests.progress(db, G, U, "work", now=NOW) == []
    assert [r.name for r in quests.progress(db, G, U, "work", now=NOW)] == ["Hard Worker"]
    assert quests.progress(db, G, U, "work", now=NOW) == []  # already done
    quests.progress(db, G, U, "rob", now=NOW)
    done = quests.progress(db, G, U, "lottery", 5, now=NOW)
    assert [r.name for r in done] == ["Feeling Lucky", "All Done!"]
    assert db.balance(G, U) == 1000 + 300 + 500 + 300 + config.QUEST_ALL_DONE_BONUS
    # a new day starts fresh
    assert quests.progress(db, G, U, "work", now=NOW + 86400) == []
    assert [p for _, p, _ in quests.status(db, G, U, now=NOW + 86400)][0] == 1


def test_games_count_toward_quests(monkeypatch):
    force_quests(monkeypatch, ["play_10", "mult_5x", "slots_10"])
    db = make()
    for _ in range(9):
        quests.on_game(db, G, U, "slots", 10, 0, now=NOW)
    done = quests.on_game(db, G, U, "slots", 10, 100, now=NOW)  # 10th game, 10x win
    assert {r.name for r in done} == {"Regular", "Lucky Break", "Reel Deal", "All Done!"}


def test_old_quest_progress_is_pruned():
    db = make()
    db.bump_counter(G, U, "q:20260901:work_2")
    db.bump_counter(G, U, "q:20260930:work_2")
    db.bump_counter(G, U, "rob_success")
    db.prune_quest_counters("20260929")
    assert db.counter(G, U, "q:20260901:work_2") == 0
    assert db.counter(G, U, "q:20260930:work_2") == 1 and db.counter(G, U, "rob_success") == 1


# ---- pets and perks -------------------------------------------------------------------------

def test_pet_perks():
    db = make(100_000)
    assert perks.work_multiplier(db, G, U) == 1.0 and perks.work_cooldown(db, G, U) == config.WORK_COOLDOWN
    for pet in ("cat", "parrot", "octopus", "laptop"):
        db.add_item(G, U, pet)
    assert perks.work_multiplier(db, G, U) == pytest.approx(1.5 * 1.1)
    assert perks.daily_multiplier(db, G, U) == 1.1
    assert perks.work_cooldown(db, G, U) == config.WORK_COOLDOWN - 15 * 60
    assert [p.key for p in perks.pets(db, G, U)] == ["cat", "parrot", "octopus"]


def test_turtle_adds_interest():
    db = make()
    db.set_bank(G, U, 10_000, 1.0)
    db.add_item(G, U, "turtle")
    assert bank.accrue(db, G, U, 1, now=1.0 + bank.DAY) == 200


class Roll(random.Random):
    def __init__(self, roll):
        super().__init__(0)
        self.roll = roll

    def random(self):
        return self.roll

    def randint(self, a, b):
        return a


def test_guard_dog_lowers_robbery_odds():
    db = make()
    roll = config.ROB_SUCCESS_CHANCE - 0.05  # would succeed normally
    assert attempt_rob(db, G, U, 2, Roll(roll)).result.value == "success"
    db2 = make()
    db2.add_item(G, 2, "dog")
    assert attempt_rob(db2, G, U, 2, Roll(roll)).result.value == "caught"


# ---- server events ----------------------------------------------------------------------------

def test_server_event_lifecycle():
    db = make()
    assert server_events.active(db, G, NOW) is None
    ends = server_events.start(db, G, "lucky_hour", 30, now=NOW)
    assert server_events.is_active(db, G, "lucky_hour", NOW) and not server_events.is_active(db, G, "xp_boost", NOW)
    assert server_events.expired(db, NOW) == []
    assert [e.key for _, e in server_events.expired(db, ends)] == ["lucky_hour"]
    assert server_events.stop(db, G).key == "lucky_hour" and server_events.active(db, G, NOW) is None


def test_lucky_hour_adds_bonus_to_wins_only():
    db = make()
    bot = fake_bot(db)
    server_events.start(db, G, "lucky_hour", 60)
    _, rewards = settle(bot, G, U, 100, 200, "coinflip")
    bonus = 200 * config.LUCKY_HOUR_BONUS_PERCENT // 100
    assert any(r.badge.startswith("🍀") and r.reward == bonus for r in rewards)
    first_win = 250
    assert db.balance(G, U) == 1000 + 200 + bonus + first_win
    _, rewards = settle(bot, G, U, 100, 0, "coinflip")
    assert not any(r.badge.startswith("🍀") for r in rewards)


# ---- stocks --------------------------------------------------------------------------------

def test_market_starts_at_base_prices_and_moves_hourly():
    db = make()
    prices = stocks.ensure(db, G, now=NOW)
    assert prices == {s: st.base for s, st in stocks.STOCKS.items()}
    assert stocks.update_due(db, G, now=NOW + 3599) == []
    moves = stocks.update_due(db, G, now=NOW + 3 * 3600 + 5, rng=random.Random(1))
    assert len(moves) == len(stocks.STOCKS)
    assert all(ts == NOW + 3 * 3600 for _, ts in db.stock_prices(G).values())
    assert stocks.update_due(db, G, now=NOW + 3 * 3600 + 10) == []


def test_prices_stay_sane_over_a_long_time():
    rng = random.Random(5)
    for stock in stocks.STOCKS.values():
        price = stock.base
        for _ in range(24 * 365):
            price = stocks.step(stock, price, rng)
        assert 1.0 <= price < stock.base * 20


def test_buy_and_sell_with_fees():
    db = make(100_000)
    stocks.ensure(db, G)
    result, cost = stocks.buy(db, G, U, "KELP", 10)
    assert result is stocks.TradeResult.OK and cost == 1010  # 100 x 10 + 1% fee
    assert db.holdings(G, U) == {"KELP": (10, 1010)}
    assert stocks.portfolio_value(db, G, U) == 1000
    assert stocks.sell(db, G, U, "KELP", 11)[0] is stocks.TradeResult.NOT_ENOUGH_SHARES
    db.set_stock_price(G, "KELP", 200.0, NOW)
    result, value, profit = stocks.sell(db, G, U, "KELP", 5)
    assert (value, profit) == (990, 990 - 505) and db.holdings(G, U) == {"KELP": (5, 505)}
    stocks.sell(db, G, U, "KELP", 5)
    assert db.holdings(G, U) == {}


def test_cant_buy_without_money():
    db = make(50)
    assert stocks.buy(db, G, U, "PRL", 1)[0] is stocks.TradeResult.CANT_AFFORD
    assert db.balance(G, U) == 50 and db.holdings(G, U) == {}


def test_holdings_wiped_by_economy_reset():
    db = make(10_000)
    stocks.buy(db, G, U, "CRAB", 5)
    db.reset_economy(G)
    assert db.holdings(G, U) == {}


# ---- heists and races -------------------------------------------------------------------------

def test_heist_odds_favour_the_house_but_reward_crews():
    for crew in range(2, 11):
        assert 0.9 < heist.success_chance(crew) * heist.multiplier(crew) < 1.0
    assert heist.success_chance(4) > heist.success_chance(2)


def test_horse_payouts_favour_the_house():
    assert sum(h.chance for h in horses.HORSES) == pytest.approx(1.0)
    for h in horses.HORSES:
        assert 0.9 < h.chance * h.payout < 1.0


def test_race_frames_end_with_the_winner_alone_at_the_line():
    rng = random.Random(3)
    for _ in range(100):
        winner = horses.pick_winner(rng)
        frames = horses.race_frames(winner, rng)
        assert len(frames) == horses.FRAMES
        assert frames[-1][winner.number - 1] == horses.TRACK_LENGTH
        assert sum(p == horses.TRACK_LENGTH for p in frames[-1]) == 1
        assert all(max(f) < horses.TRACK_LENGTH for f in frames[:-1])


# ---- alt protection and game toggles -------------------------------------------------------------

def test_trust_rules():
    db = make()
    cfg = settings.load(db, G)
    now = dt.datetime(2026, 9, 30, tzinfo=dt.timezone.utc)
    old = dt.datetime(2020, 1, 1, tzinfo=dt.timezone.utc)
    assert trust_problem(SimpleNamespace(created_at=old, joined_at=old), cfg, now) is None
    fresh = SimpleNamespace(created_at=now - dt.timedelta(days=2), joined_at=old)
    assert "7 days old" in trust_problem(fresh, cfg, now)
    newcomer = SimpleNamespace(created_at=old, joined_at=now - dt.timedelta(hours=3))
    assert "1 day" in trust_problem(newcomer, cfg, now)
    settings.save(db, G, "min_account_age_days", 0)
    settings.save(db, G, "min_server_days", 0)
    assert trust_problem(fresh, settings.load(db, G), now) is None


def test_game_toggles():
    db = make()
    settings.set_game_enabled(db, G, "crash", False)
    settings.set_game_enabled(db, G, "mines", False)
    settings.set_game_enabled(db, G, "crash", True)
    assert settings.load(db, G).disabled_games == {"mines"}
    assert settings.load(db, 2).disabled_games == frozenset()


# ---- tracker lines for the new history ------------------------------------------------------------

def test_tracker_shows_new_events_and_running_event():
    db = make()
    cfg = settings.load(db, G)
    db.add_event(G, "heist", 1, 3000, amount2=3, detail="success", ts=NOW - 3)
    db.add_event(G, "promotion", 2, 5, detail="Lifeguard", ts=NOW - 2)
    db.add_event(G, "stock", amount=-1234, amount2=4321, detail="CRAB", ts=NOW - 1)
    body = tracker.history_embed(db, G, cfg, NOW).description
    assert "crew of 3" in body and "promoted to **Lifeguard**" in body and "**CRAB** dropped 12.3% to 43.21" in body
    server_events.start(db, G, "double_pay", 60, now=NOW)
    assert "Double Pay is on!" in tracker.overview_embed(db, G, cfg, NOW, "T").description
