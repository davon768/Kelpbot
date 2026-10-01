"""/games: the list, the Play menu, and starting games from the bet form."""

from conftest import GUILD, FIRST_WIN, FakeInteraction, FakeMember, call
from kelpbot import settings
from kelpbot.cogs.games import BY_KEY, GAMES
from kelpbot.settings import GAMES as TOGGLEABLE


def open_menu(kb, who):
    it = call(kb, "games", who)
    return it, it.sent[-1].view


def pick(kb, view, key, who):
    it = FakeInteraction(who)
    view.select._values = [key]

    async def click():
        if await view.interaction_check(it):
            await view.select.callback(it)

    kb.run(click())
    return it


def submit(kb, modal, who, **values):
    for param, (field, text) in modal.inputs.items():
        text._value = values.get(param, field.default)
    it = FakeInteraction(who)
    kb.run(modal.on_submit(it))
    return it


def test_lists_every_game():
    assert set(TOGGLEABLE) - {"stocks"} == {g.key for g in GAMES}


def test_menu_lists_games_and_hides_switched_off_ones(kb):
    settings.set_game_enabled(kb.db, GUILD, "crash", False)
    it, view = open_menu(kb, FakeMember(1))
    assert it.sent[-1].ephemeral
    assert "~~🚀 Crash~~" in it.last_text and "**Slots**" in it.last_text
    options = {o.value for o in view.select.options}
    assert "crash" not in options and "duel" not in options and "slots" in options


def test_only_the_owner_can_use_the_menu(kb):
    _, view = open_menu(kb, FakeMember(1))
    it = pick(kb, view, "slots", FakeMember(2))
    assert it.modal is None and "your own menu" in it.last_text


def test_play_slots_from_the_menu(kb):
    alice = FakeMember(1)
    _, view = open_menu(kb, alice)
    modal = pick(kb, view, "slots", alice).modal
    assert modal.title == "Play Slots" and list(modal.inputs) == ["bet"]
    assert "Between 10 and 50,000" in modal.inputs["bet"][1].placeholder
    import asyncio
    from conftest import noop
    real_sleep = asyncio.sleep
    asyncio.sleep = noop  # skip the reel animation
    try:
        it = submit(kb, modal, alice, bet="100")
    finally:
        asyncio.sleep = real_sleep
    assert kb.db.account(GUILD, 1).games_played == 1
    assert "Slots" in it.last_text


def test_coinflip_form_parses_side(kb):
    alice = FakeMember(1)
    _, view = open_menu(kb, alice)
    modal = pick(kb, view, "coinflip", alice).modal
    it = submit(kb, modal, alice, bet="1,000", side="T")
    assert "You picked tails" in it.sent[-1].embed.footer.text
    assert kb.db.balance(GUILD, 1) in (0, 2000 + FIRST_WIN)


def test_bad_input_is_explained_and_costs_nothing(kb):
    alice = FakeMember(1)
    _, view = open_menu(kb, alice)
    modal = pick(kb, view, "coinflip", alice).modal
    it = submit(kb, modal, alice, bet="lots", side="heads")
    assert it.sent[-1].ephemeral and "Bet needs to be a whole number" in it.last_text
    it = submit(kb, modal, alice, bet="100", side="edge")
    assert "must be heads or tails" in it.last_text
    assert kb.db.balance(GUILD, 1) == 1000


def test_server_bet_limits_still_apply(kb):
    alice = FakeMember(1)
    settings.save(kb.db, GUILD, "max_bet", 200)
    _, view = open_menu(kb, alice)
    modal = pick(kb, view, "dice", alice).modal
    it = submit(kb, modal, alice, bet="500", chance="50")
    assert "maximum bet" in it.last_text and kb.db.balance(GUILD, 1) == 1000


def test_interactive_and_group_games_start(kb):
    alice = FakeMember(1)
    _, view = open_menu(kb, alice)
    it = submit(kb, pick(kb, view, "mines", alice).modal, alice, bet="100", mines="2")
    assert len(it.sent[-1].view.game.mine_tiles) == 2
    _, view = open_menu(kb, alice)
    lottery = pick(kb, view, "lottery", alice).modal
    assert list(lottery.inputs) == ["tickets"]
    submit(kb, lottery, alice, tickets="3")
    assert kb.db.lottery_tickets(GUILD) == {1: 3}


def test_crash_auto_cashout_is_optional():
    parse = BY_KEY["crash"].fields[0].parse
    assert parse("") is None and parse("2.5x") == 2.5
