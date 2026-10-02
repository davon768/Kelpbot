import random
import re

from conftest import FakeMember, call
from kelpbot import facts
from kelpbot.db import Database


def normalized(text):
    return re.sub(r"[^a-z0-9]", "", text.lower())


def test_lists_are_large_and_have_no_duplicates():
    assert len(facts.FUN.facts) >= 500 and len(facts.NOT_FUN.facts) >= 300
    for deck in (facts.FUN, facts.NOT_FUN):
        seen = [normalized(f.text) for f in deck.facts]
        dupes = {f.text for f in deck.facts if seen.count(normalized(f.text)) > 1}
        assert not dupes, dupes
    shared = {normalized(f.text) for f in facts.FUN.facts} & {normalized(f.text) for f in facts.NOT_FUN.facts}
    assert not shared


def test_facts_fit_in_a_discord_embed_and_read_as_sentences():
    for deck in (facts.FUN, facts.NOT_FUN):
        for f in deck.facts:
            assert 10 < len(f.text) < 4096, f.text
            assert f.text[-1] in ".!?\"”)", f.text


def test_not_so_fun_categories():
    assert {f.category for f in facts.NOT_FUN.facts} == {"Sad", "Dark", "Uninteresting"}


def test_no_repeats_until_every_fact_has_been_shown():
    db = Database(":memory:", 1000)
    deck = facts.Deck("test", tuple(facts.Fact(f"Fact number {i}.", "Misc") for i in range(50)))
    rng = random.Random(1)
    first_cycle = [facts.next_fact(db, 1, deck, rng) for _ in range(50)]
    assert [n for _, n in first_cycle] == list(range(1, 51))
    assert len({f.text for f, _ in first_cycle}) == 50
    last = first_cycle[-1][0]
    second, number = facts.next_fact(db, 1, deck, rng)
    assert number == 1 and second != last  # a fresh cycle that doesn't open with the fact just shown
    rest = [facts.next_fact(db, 1, deck, rng)[0] for _ in range(49)]
    assert len({f.text for f in [second, *rest]}) == 50


def test_each_server_has_its_own_place():
    db = Database(":memory:", 1000)
    for _ in range(5):
        facts.next_fact(db, 1, facts.FUN)
    assert facts.next_fact(db, 2, facts.FUN)[1] == 1
    assert facts.next_fact(db, 1, facts.FUN)[1] == 6


def test_order_survives_a_restart(tmp_path):
    path = str(tmp_path / "kelpbot.db")
    db = Database(path, 1000)
    shown = [facts.next_fact(db, 1, facts.FUN)[0] for _ in range(3)]
    db.close()
    db = Database(path, 1000)
    fact, number = facts.next_fact(db, 1, facts.FUN)
    assert number == 4 and fact not in shown


def test_editing_the_list_starts_a_fresh_cycle():
    db = Database(":memory:", 1000)
    small = facts.Deck("edit", tuple(facts.Fact(f"Fact {i}.", "Misc") for i in range(10)))
    for _ in range(4):
        facts.next_fact(db, 1, small)
    bigger = facts.Deck("edit", small.facts + (facts.Fact("A brand new fact.", "Misc"),))
    assert facts.next_fact(db, 1, bigger)[1] == 1


def test_funfact_commands(kb):
    alice = FakeMember(1)
    it = call(kb, "funfact", alice)
    msg = it.sent[-1]
    assert not msg.ephemeral and msg.embed.title == "💡 Fun fact"
    assert msg.embed.footer.text.endswith(f"1 of {len(facts.FUN.facts)}")
    blocked = call(kb, "notsofunfact", alice)  # the cooldown is shared between both commands
    assert blocked.sent[-1].ephemeral and "Give it" in blocked.last_text
    other = call(kb, "notsofunfact", FakeMember(2))
    assert "Not-so-fun fact" in other.sent[-1].embed.title
    assert other.sent[-1].embed.footer.text.split(" · ")[0] in {"Sad", "Dark", "Uninteresting"}
    for name in ("funfact", "notsofunfact"):
        assert kb.tree.get_command(name).extras.get("manual_cleanup")  # facts aren't auto-deleted
