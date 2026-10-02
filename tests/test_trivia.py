import asyncio
import random
import re

import pytest

from conftest import GUILD, FakeInteraction, FakeMember, call, loaded
from kelpbot import config, settings
from kelpbot import trivia as bank

ROMAN_VALUES = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}


def from_roman(s):
    total = 0
    for a, b in zip(s, s[1:] + " "):
        v = ROMAN_VALUES[a]
        total += -v if b != " " and ROMAN_VALUES[b] > v else v
    return total


# ---- the bank ------------------------------------------------------------------------

def test_a_couple_thousand_questions_in_every_topic():
    assert len(bank.BANK) >= 2000
    assert all(len(qs) >= 150 for qs in bank.BY_TOPIC.values())
    assert set(bank.RANDOM_WEIGHTS) == set(bank.TOPICS)


def test_every_question_is_well_formed():
    prompts = set()
    for q in bank.BANK:
        assert q.prompt not in prompts, q.prompt
        prompts.add(q.prompt)
        assert q.difficulty in bank.DIFFICULTIES and q.topic in bank.TOPICS
        wrong = {w.strip().lower() for w in q.wrong_pool}
        assert len(wrong) >= 3, q.prompt
        assert q.answer.strip().lower() not in wrong, q.prompt
        assert all(len(f"D. {option}") <= 80 for option in (q.answer, *q.wrong_pool)), q.prompt  # button limit


def test_options_are_four_distinct_choices_including_the_answer():
    rng = random.Random(1)
    for q in rng.sample(bank.BANK, 300):
        options, correct = q.options(rng)
        assert len(options) == 4 == len(set(options)) and options[correct] == q.answer


def test_handwritten_questions_have_exactly_three_wrong_answers():
    general = bank.load_general()
    assert len(general) >= 400
    assert all(len(q.wrong_pool) == 3 for q in general)
    assert {q.category for q in general} >= {"Science", "History", "Geography", "Animals", "Sports"}


def test_lookalike_flags_never_appear_together():
    by_prompt = {q.prompt: q for q in bank.BY_TOPIC["flags"]}
    chad = by_prompt[f"Which country does this flag belong to? {bank.flag_emoji('TD')}"]
    assert chad.answer == "Chad" and "Romania" not in chad.wrong_pool
    indonesia = by_prompt[f"Which country does this flag belong to? {bank.flag_emoji('ID')}"]
    assert "Monaco" not in indonesia.wrong_pool


def test_country_questions_read_naturally_and_skip_disputed_answers():
    prompts = {q.prompt for q in bank.BANK}
    assert "What is the capital of the United Kingdom?" in prompts
    assert "What is the capital of Bolivia?" not in prompts  # La Paz or Sucre: left out on purpose
    assert "Which continent is Russia in?" not in prompts  # spans two continents
    assert "Kuwait City is the capital of which country?" not in prompts  # gives the answer away


def test_roman_numerals_are_correct():
    for n in (1, 4, 9, 14, 40, 90, 400, 1066, 1776, 1999, 2024, 3999):
        assert from_roman(bank.to_roman(n)) == n
    for q in bank.BY_TOPIC["roman"]:
        if q.prompt.startswith("How is"):
            n = int(re.search(r"How is (\d+)", q.prompt).group(1))
            assert from_roman(q.answer) == n and all(from_roman(w) != n for w in q.wrong_pool)
        else:
            assert from_roman(re.search(r"What number is ([IVXLCDM]+)", q.prompt).group(1)) == int(q.answer)


def test_data_tables():
    countries = bank._rows("countries.tsv")
    assert len(countries) == 194 and len({r[0] for r in countries}) == 194
    assert {r[3] for r in countries} <= set(bank.CONTINENTS) | {"-"}
    assert len(bank._rows("us_states.tsv")) == 50 and len(bank._rows("elements.tsv")) == 118


# ---- playing ----------------------------------------------------------------------------

@pytest.fixture
def quick(monkeypatch):
    monkeypatch.setattr(config, "TRIVIA_SECONDS", 0.05)


def play(kb, starter, answers, topic=None):
    """Start /trivia, have each (member, pick) answer, and wait for the result."""

    async def run():
        it = FakeInteraction(starter)
        cmd = kb.tree.get_command("trivia")
        task = asyncio.ensure_future(cmd.callback(cmd.binding, it, topic=topic))
        while not it.sent:
            await asyncio.sleep(0)
        view = it.sent[-1].view
        clicks = []
        for member, pick in answers:
            choice = view.correct if pick == "right" else (view.correct + 1) % 4
            click = FakeInteraction(member)
            await view.buttons[choice].callback(click)
            clicks.append(click)
        await task
        return it, view, clicks

    return kb.run(run())


def test_correct_answers_are_paid_and_the_first_gets_a_bonus(kb, quick):
    alice, bob, carol = FakeMember(1, "Alice"), FakeMember(2, "Bob"), FakeMember(3, "Carol")
    it, view, clicks = play(kb, alice, [(bob, "right"), (carol, "wrong"), (alice, "right")])
    base = config.TRIVIA_REWARDS[view.question.difficulty]
    assert kb.db.balance(GUILD, 2) == 1000 + base + base * config.TRIVIA_FIRST_BONUS_PERCENT // 100
    assert kb.db.balance(GUILD, 1) == 1000 + base
    assert kb.db.balance(GUILD, 3) == 1000
    result = it.message.edits[-1]["embed"]
    assert "The answer was" in result.description and "(first!)" in result.description
    assert "1 wrong answer" in result.description
    assert all(b.disabled for b in view.buttons)
    assert view.buttons[view.correct].style.name == "success"
    assert all(c.sent[-1].ephemeral for c in clicks)


def test_one_answer_each_and_none_after_time_is_up(kb, quick):
    bob = FakeMember(2)

    async def run():
        it = FakeInteraction(FakeMember(1))
        cmd = kb.tree.get_command("trivia")
        task = asyncio.ensure_future(cmd.callback(cmd.binding, it, topic="general"))
        while not it.sent:
            await asyncio.sleep(0)
        view = it.sent[-1].view
        await view.buttons[view.correct].callback(FakeInteraction(bob))
        again = FakeInteraction(bob)
        await view.buttons[(view.correct + 1) % 4].callback(again)
        await task
        late = FakeInteraction(FakeMember(3))
        await view.buttons[0].callback(late)
        return view, again, late

    view, again, late = kb.run(run())
    assert "already answered" in again.last_text and "Too late" in late.last_text
    assert view.question.topic == "general"
    assert kb.db.balance(GUILD, 2) > 1000  # the first (right) answer counted


def test_daily_cap_limits_earnings(kb, quick):
    from kelpbot.cogs.trivia import earned_key
    kb.db.bump_counter(GUILD, 2, earned_key(), config.TRIVIA_DAILY_CAP - 40)
    it, _, _ = play(kb, FakeMember(1), [(FakeMember(2), "right")])
    assert kb.db.balance(GUILD, 2) == 1040
    assert "daily trivia limit" in it.message.edits[-1]["embed"].description


def test_one_question_per_channel_and_start_cooldown(kb, monkeypatch):
    trivia_cog = kb.get_cog("Trivia")
    trivia_cog.active_channels.add(50)
    assert "already running" in call(kb, "trivia", FakeMember(1)).last_text
    trivia_cog.active_channels.clear()
    kb.db.mark_used(GUILD, 1, "trivia")
    assert "start another question" in call(kb, "trivia", FakeMember(1)).last_text


def test_trivia_can_be_switched_off(kb):
    settings.set_game_enabled(kb.db, GUILD, "trivia", False)
    assert "turned off" in call(kb, "trivia", FakeMember(1)).last_text


def test_questions_do_not_repeat_within_a_topic(kb, quick):
    seen = set()
    for i in range(30):
        _, view, _ = play(kb, FakeMember(100 + i), [], topic="flags")
        seen.add(view.question.prompt)
    assert len(seen) == 30


def test_start_from_the_games_menu(kb, quick):
    games = loaded("kelpbot.cogs.games")
    alice = FakeMember(1)
    view = call(kb, "games", alice).sent[-1].view
    assert "trivia" in {o.value for o in view.select.options}
    it = FakeInteraction(alice)
    view.select._values = ["trivia"]
    kb.run(view.select.callback(it))
    assert it.modal is None and "Trivia" in it.sent[-1].embed.title
    assert games.BY_KEY["trivia"].has_bet is False
