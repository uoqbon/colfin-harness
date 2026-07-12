"""Discord front-end message handling — pure functions only. No discord.Client
is instantiated and no network is touched; the gating, chunking, allowlist
parsing, and per-channel history logic all test offline."""

from colfin_harness.config import Settings
from colfin_harness.conversation import MAX_HISTORY_TURNS
from colfin_harness.discord_bot import (
    DISCORD_MESSAGE_LIMIT,
    chunk_message,
    record_turn,
    should_respond,
    strip_bot_mention,
)
from colfin_harness.orchestrator import Turn

ALLOWED = frozenset({111, 222})


# --- should_respond gating -------------------------------------------------


def test_allowed_dm_is_answered():
    assert should_respond(111, is_dm=True, mentions_bot=False, allowlist=ALLOWED)


def test_non_allowlisted_dm_is_ignored():
    assert not should_respond(999, is_dm=True, mentions_bot=False, allowlist=ALLOWED)


def test_guild_message_without_mention_is_ignored():
    assert not should_respond(111, is_dm=False, mentions_bot=False, allowlist=ALLOWED)


def test_guild_mention_from_allowlisted_user_is_answered():
    assert should_respond(111, is_dm=False, mentions_bot=True, allowlist=ALLOWED)


def test_empty_allowlist_fails_closed():
    assert not should_respond(111, is_dm=True, mentions_bot=True, allowlist=frozenset())


def test_bot_author_is_ignored_even_if_allowlisted():
    assert not should_respond(
        111, is_dm=True, mentions_bot=True, allowlist=ALLOWED, author_is_bot=True
    )


# --- mention stripping -----------------------------------------------------


def test_strip_bot_mention_handles_both_forms():
    assert strip_bot_mention("<@42> quote TEL", 42) == "quote TEL"
    assert strip_bot_mention("<@!42> quote TEL", 42) == "quote TEL"
    assert strip_bot_mention("quote <@42> TEL", 42) == "quote  TEL"


def test_strip_bot_mention_ignores_ids_with_bot_prefix():
    assert strip_bot_mention("<@421> hi <@42>", 42) == "<@421> hi"


def test_strip_bot_mention_leaves_other_mentions():
    assert strip_bot_mention("<@42> ask <@77>", 42) == "ask <@77>"


# --- chunking --------------------------------------------------------------


def test_short_message_is_one_chunk():
    assert chunk_message("hello") == ["hello"]


def test_chunks_respect_discord_limit():
    text = "x" * 4500
    chunks = chunk_message(text)
    assert all(len(c) <= DISCORD_MESSAGE_LIMIT for c in chunks)
    assert "".join(chunks) == text  # content preserved


def test_chunking_prefers_newline_splits():
    lines = [f"line {i:04d} " + "y" * 90 for i in range(60)]
    text = "\n".join(lines)
    chunks = chunk_message(text)
    assert all(len(c) <= DISCORD_MESSAGE_LIMIT for c in chunks)
    assert "".join(chunks) == text
    # Every chunk but the last ends at a line boundary, not mid-line.
    assert all(c.endswith("\n") for c in chunks[:-1])


def test_empty_text_yields_no_chunks():
    assert chunk_message("") == []


def test_exactly_limit_is_one_chunk():
    assert chunk_message("x" * DISCORD_MESSAGE_LIMIT) == ["x" * DISCORD_MESSAGE_LIMIT]


def test_one_over_limit_splits_hard_at_limit():
    text = "x" * (DISCORD_MESSAGE_LIMIT + 1)
    assert chunk_message(text) == ["x" * DISCORD_MESSAGE_LIMIT, "x"]


# --- allowlist parsing from Settings ----------------------------------------


def test_allowlist_parses_comma_separated_ids():
    s = Settings(discord_allowed_users="123456789012345678, 42")
    assert s.discord_allowed_user_ids == frozenset({123456789012345678, 42})


def test_allowlist_ignores_blank_entries():
    s = Settings(discord_allowed_users=" , 7 ,,  ")
    assert s.discord_allowed_user_ids == frozenset({7})


def test_allowlist_skips_invalid_entries_instead_of_raising():
    # A typo in the env var must not crash the bot thread; it fails closed.
    s = Settings(discord_allowed_users="12345;67890, 7, oops")
    assert s.discord_allowed_user_ids == frozenset({7})


def test_allowlist_default_is_empty():
    assert Settings().discord_allowed_user_ids == frozenset()


# --- per-channel history ----------------------------------------------------


def test_record_turn_keeps_channels_independent():
    histories: dict[int, list[Turn]] = {}
    record_turn(histories, 100, "q-a", "ans-a")
    record_turn(histories, 200, "q-b", "ans-b")
    assert histories[100] == [Turn("q-a", "ans-a")]
    assert histories[200] == [Turn("q-b", "ans-b")]


def test_record_turn_trims_with_shared_bounds():
    histories: dict[int, list[Turn]] = {}
    for i in range(MAX_HISTORY_TURNS + 4):
        record_turn(histories, 100, f"q{i}", f"a{i}")
    history = histories[100]
    assert len(history) == MAX_HISTORY_TURNS
    assert history[-1] == Turn(f"q{MAX_HISTORY_TURNS + 3}", f"a{MAX_HISTORY_TURNS + 3}")
