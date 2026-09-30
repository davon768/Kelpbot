"""Fake Discord objects and a bot fixture shared by the command and tracker tests."""

import asyncio
import itertools
from types import SimpleNamespace

import pytest

import bot as bot_module
from kelpbot import config

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


async def noop(*_args, **_kwargs):
    return None
