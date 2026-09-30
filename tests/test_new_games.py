import random

from kelpbot.games import crash, dice, highlow, mines


def test_crash_manual_cash_out():
    g = crash.CrashGame(bet=100, crash_at=5.0, started=0.0)
    t = crash.multiplier_at(1)  # one second in
    assert g.cash_out(1.0) and g.cashed_out == t and g.payout() == int(100 * t)
    assert not g.cash_out(2.0)  # can't cash out twice


def test_crash_too_late():
    g = crash.CrashGame(bet=100, crash_at=1.5, started=0.0)
    assert not g.cash_out(60.0)
    assert g.crashed and g.payout() == 0


def test_crash_auto_cash_out_pays_exact_target():
    g = crash.CrashGame(bet=100, crash_at=3.0, started=0.0, auto_cashout=2.0)
    g.tick(30.0)  # long after both points: auto cash-out wins because it comes first
    assert g.cashed_out == 2.0 and g.payout() == 200


def test_crash_auto_target_above_crash_loses():
    g = crash.CrashGame(bet=100, crash_at=1.8, started=0.0, auto_cashout=2.0)
    g.tick(30.0)
    assert g.crashed and g.payout() == 0


def test_crash_house_edge():
    rng = random.Random(3)
    points = [crash.crash_point(rng) for _ in range(100_000)]
    assert min(points) >= 1.0 and max(points) <= crash.MAX_MULTIPLIER
    rtp = sum(p >= 2.0 for p in points) / len(points) * 2
    assert 0.95 < rtp < 1.0


def test_mines_multiplier_grows_and_edge_applies():
    assert mines.multiplier(3, 0) == 1.0
    assert mines.multiplier(3, 1) < mines.multiplier(3, 2) < mines.multiplier(5, 2)
    assert mines.multiplier(1, 1) == round(20 / 19 * mines.HOUSE_EDGE, 2)


def test_mines_hit_mine():
    g = mines.MinesGame(bet=100, mines=2, mine_tiles={0, 1})
    assert g.reveal(5) and not g.finished
    assert not g.reveal(0) and g.exploded and g.payout() == 0


def test_mines_cash_out_and_clear():
    g = mines.MinesGame(bet=100, mines=1, mine_tiles={0})
    assert not g.cash_out()  # need at least one pick
    g.reveal(3)
    assert g.cash_out() and g.payout() == int(100 * mines.multiplier(1, 1))
    full = mines.MinesGame(bet=100, mines=19, mine_tiles=set(range(1, 20)))
    full.reveal(0)
    assert full.cleared and full.cashed_out and full.payout() == int(100 * mines.multiplier(19, 1))


def test_mines_random_board_has_right_mine_count():
    g = mines.MinesGame(bet=1, mines=7, rng=random.Random(1))
    assert len(g.mine_tiles) == 7 and all(0 <= t < mines.TILES for t in g.mine_tiles)


class Deck(random.Random):
    def __init__(self, cards):
        super().__init__(0)
        self.cards = list(cards)

    def randint(self, a, b):
        return self.cards.pop(0)


def test_highlow_win_then_lose():
    g = highlow.HighLowGame(bet=100, rng=Deck([5, 9, 9]))
    assert g.guess(higher=True) and g.streak == 1
    assert g.multiplier == highlow.guess_multiplier(5, True)
    assert not g.guess(higher=True)  # 9 -> 9 is a tie, which loses
    assert g.lost and g.payout() == 0


def test_highlow_impossible_guess_refused_and_cash_out():
    g = highlow.HighLowGame(bet=100, rng=Deck([13, 2]))
    assert highlow.guess_multiplier(13, True) is None
    assert not g.guess(higher=True) and not g.finished
    assert not g.cash_out()  # nothing won yet
    assert g.guess(higher=False)
    assert g.cash_out() and g.payout() == int(100 * g.multiplier)


def test_highlow_edge_below_one():
    # expected value of any single guess is the house edge
    for card in range(1, 14):
        for higher in (True, False):
            m = highlow.guess_multiplier(card, higher)
            if m:
                assert abs(m * highlow.winning_cards(card, higher) / 13 - highlow.HOUSE_EDGE) < 0.02


def test_dice():
    assert dice.multiplier(50) == 1.96
    assert dice.payout(100, 50, 50) == 196
    assert dice.payout(100, 50, 51) == 0
    assert dice.payout(100, 1, 1) == 9800
