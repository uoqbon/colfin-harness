"""Conversational REPL behavior — exit/EOF, blank-line skipping, history
carry/trim, and one silent re-login on expiry. Driven by a scripted
orchestrator and fake input; no browser, model, or network."""

import builtins
import threading
from concurrent.futures import ThreadPoolExecutor

from colfin_harness import __main__ as cli
from colfin_harness.exceptions import LoginFailed, SessionExpired
from colfin_harness.orchestrator import Turn


class FakeOrchestrator:
    def __init__(self, answers):
        self.answers = list(answers)
        self.calls = []

    def run(self, task, history=None):
        self.calls.append((task, list(history or [])))
        result = self.answers.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


class FakeSession:
    def __init__(self, relogin_error=None):
        self.relogins = 0
        self._relogin_error = relogin_error

    def relogin(self):
        self.relogins += 1
        if self._relogin_error is not None:
            raise self._relogin_error


def _feed(monkeypatch, lines):
    it = iter(lines)
    monkeypatch.setattr(builtins, "input", lambda *a: next(it))


def test_exits_on_exit_and_records_turn(monkeypatch):
    _feed(monkeypatch, ["quote TEL", "exit"])
    orch = FakeOrchestrator(["TEL 13.50"])
    history = []
    cli.run_repl(orch, FakeSession(), history)
    assert [c[0] for c in orch.calls] == ["quote TEL"]
    assert history == [Turn("quote TEL", "TEL 13.50")]


def test_skips_blank_lines(monkeypatch):
    _feed(monkeypatch, ["", "   ", "hello", "exit"])
    orch = FakeOrchestrator(["hi"])
    cli.run_repl(orch, FakeSession(), [])
    assert [c[0] for c in orch.calls] == ["hello"]


def test_exits_on_eof(monkeypatch):
    def raise_eof(*a):
        raise EOFError

    monkeypatch.setattr(builtins, "input", raise_eof)
    cli.run_repl(FakeOrchestrator([]), FakeSession(), [])  # returns cleanly


def test_carries_history_into_next_turn(monkeypatch):
    _feed(monkeypatch, ["q1", "q2", "exit"])
    orch = FakeOrchestrator(["a1", "a2"])
    cli.run_repl(orch, FakeSession(), [])
    assert orch.calls[1][1] == [Turn("q1", "a1")]  # second call saw the first turn


def test_keeps_going_after_tool_error(monkeypatch, capsys):
    _feed(monkeypatch, ["boom", "ok", "exit"])
    orch = FakeOrchestrator([RuntimeError("tool blew up"), "fine"])
    history = []
    cli.run_repl(orch, FakeSession(), history)
    assert history == [Turn("ok", "fine")]  # failed turn not recorded
    assert "Error: RuntimeError" in capsys.readouterr().out


def test_breaks_when_relogin_fails(monkeypatch, capsys):
    _feed(monkeypatch, ["q", "unreached", "exit"])
    orch = FakeOrchestrator([SessionExpired("gone")])
    session = FakeSession(relogin_error=LoginFailed("no creds"))
    cli.run_repl(orch, session, [])
    assert session.relogins == 1
    assert "Re-login failed" in capsys.readouterr().out
    assert len(orch.calls) == 1  # loop broke; "unreached" never ran


def test_answer_task_relogins_once_then_succeeds():
    orch = FakeOrchestrator([SessionExpired("gone"), "recovered"])
    session = FakeSession()
    out = cli.answer_task(orch, session, "q", [])
    assert out == "recovered"
    assert session.relogins == 1


def test_trim_history_bounds_turn_count():
    history = [Turn(f"q{i}", f"a{i}") for i in range(10)]
    cli.trim_history(history)
    assert len(history) == cli.MAX_HISTORY_TURNS
    assert history[-1] == Turn("q9", "a9")  # newest retained


def test_trim_history_bounds_chars():
    big = "x" * 5000  # two of these exceed MAX_HISTORY_CHARS (6000)
    history = [Turn("q0", big), Turn("q1", big)]
    cli.trim_history(history)
    assert len(history) == 1
    assert history[0].question == "q1"  # oldest dropped


class RecordingLock:
    """A context-manager lock that records which thread acquires it."""

    def __init__(self):
        self._lock = threading.Lock()
        self.acquired_on = []

    def __enter__(self):
        self._lock.acquire()
        self.acquired_on.append(threading.current_thread().name)
        return self

    def __exit__(self, *exc_info):
        self._lock.release()


def test_repl_acquires_lock_on_turn_executor_thread(monkeypatch):
    # Deadlock regression: the REPL must never hold turn_lock on the main
    # thread while waiting on the single-worker executor — a Discord turn
    # already occupying that worker (blocked on the same lock) would deadlock
    # both front-ends. The lock must be taken inside the executor task.
    _feed(monkeypatch, ["q", "exit"])
    orch = FakeOrchestrator(["a"])
    lock = RecordingLock()
    with ThreadPoolExecutor(max_workers=1, thread_name_prefix="test-turn") as executor:
        cli.run_repl(orch, FakeSession(), [], turn_lock=lock, turn_executor=executor)
    assert lock.acquired_on == ["test-turn_0"]  # executor thread, not MainThread


def test_resolve_settings_omitted_keeps_base():
    # No flag → the base settings instance is returned unchanged (env default).
    assert cli.resolve_settings(None) is cli.default_settings


def test_resolve_settings_forces_headless():
    base_before = cli.default_settings.headless
    resolved = cli.resolve_settings(True)
    assert resolved.headless is True
    assert resolved is not cli.default_settings  # a copy, not the singleton
    assert cli.default_settings.headless == base_before  # base not mutated


def test_resolve_settings_forces_headed():
    resolved = cli.resolve_settings(False)
    assert resolved.headless is False
    # Other settings carry over from the base config unchanged.
    assert resolved.base_url == cli.default_settings.base_url
