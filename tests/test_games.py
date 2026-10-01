import random
from itertools import product

from kelpbot.games import roulette, slots
from kelpbot.games.blackjack import BlackjackGame, Card, Outcome, hand_value


def c(rank):
    return Card(rank, "♠")


def test_hand_value_soft_aces():
    assert hand_value([c("A"), c("K")]) == 21
    assert hand_value([c("A"), c("A"), c("9")]) == 21
    assert hand_value([c("A"), c("9"), c("5")]) == 15
    assert hand_value([c("K"), c("Q"), c("5")]) == 25


def test_natural_blackjack_pays_3_to_2():
    g = BlackjackGame(bet=100, shoe=[c("5")], player=[c("A"), c("K")], dealer=[c("9"), c("7")])
    assert g.outcome is Outcome.BLACKJACK
    assert g.payout() == 250


def test_both_blackjack_is_push():
    g = BlackjackGame(bet=100, shoe=[c("5")], player=[c("A"), c("K")], dealer=[c("A"), c("Q")])
    assert g.outcome is Outcome.PUSH and g.payout() == 100


def test_bust_loses():
    g = BlackjackGame(bet=50, shoe=[c("K")], player=[c("10"), c("6")], dealer=[c("9"), c("7")])
    g.hit()
    assert g.outcome is Outcome.BUST and g.payout() == 0


def test_dealer_draws_to_17_and_busts():
    # shoe pops from the end
    g = BlackjackGame(bet=50, shoe=[c("K")], player=[c("10"), c("8")], dealer=[c("10"), c("6")])
    g.stand()
    assert hand_value(g.dealer) == 26
    assert g.outcome is Outcome.WIN and g.payout() == 100


def test_double_down_doubles_bet():
    g = BlackjackGame(bet=50, shoe=[c("2"), c("10")], player=[c("5"), c("6")], dealer=[c("10"), c("7")])
    g.double_down()
    assert g.doubled and g.bet == 100 and len(g.player) == 3
    assert g.outcome is Outcome.WIN and g.payout() == 200


def test_random_games_always_finish():
    rng = random.Random(1)
    for _ in range(500):
        g = BlackjackGame(bet=10, rng=rng)
        while not g.finished:
            g.hit() if hand_value(g.player) < 15 else g.stand()
        assert g.payout() in (0, 10, 20, 25)


def test_slots_rtp_favours_house():
    total = sum(s.weight for s in slots.SYMBOLS)
    rtp = 0.0
    for combo in product(slots.SYMBOLS, repeat=3):
        p = 1.0
        for s in combo:
            p *= s.weight / total
        rtp += p * slots.payout_multiplier(list(combo))
    assert 0.8 < rtp < 1.0


def test_slots_payouts():
    cherry, lemon, seven = slots.SYMBOLS[0], slots.SYMBOLS[1], slots.SYMBOLS[-1]
    assert slots.payout_multiplier([seven] * 3) == seven.triple_payout
    assert slots.payout_multiplier([cherry, lemon, cherry]) == slots.TWO_CHERRY_PAYOUT
    assert slots.payout_multiplier([cherry, lemon, seven]) == 0


def test_roulette_parsing_and_payouts():
    assert roulette.parse_choice(" Red ") == "red"
    assert roulette.parse_choice("17") == 17
    assert roulette.parse_choice("37") is None
    assert roulette.parse_choice("purple") is None
    assert roulette.payout_multiplier("red", 1) == 2
    assert roulette.payout_multiplier("black", 0) == 0
    assert roulette.payout_multiplier("even", 0) == 0
    assert roulette.payout_multiplier("2nd12", 13) == 3
    assert roulette.payout_multiplier(17, 17) == 36
    assert roulette.payout_multiplier(0, 17) == 0


def test_hitting_to_21_waits_for_the_player_to_stand():
    # shoe pops from the end: the player draws the 5, the dealer would draw the K
    g = BlackjackGame(bet=50, shoe=[c("K"), c("5")], player=[c("10"), c("6")], dealer=[c("10"), c("2")])
    g.hit()
    assert hand_value(g.player) == 21 and not g.finished
    assert len(g.dealer) == 2  # the dealer hasn't played yet
    assert not g.can_hit and not g.can_double
    g.hit()  # ignored at 21
    assert len(g.player) == 3
    g.stand()
    assert g.finished and len(g.dealer) == 3


def test_soft_21_after_hitting_also_waits():
    g = BlackjackGame(bet=50, shoe=[c("9"), c("A")], player=[c("5"), c("5")], dealer=[c("10"), c("7")])
    g.hit()
    assert hand_value(g.player) == 21 and not g.finished and not g.can_hit
