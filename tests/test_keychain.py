"""Keychain token lookup — mocked ``security`` invocations, no real Keychain.

The token is a credential: it must come from the macOS Keychain only, never
env vars (the model-server subprocess inherits the environment)."""

import subprocess
import sys

from colfin_harness import keychain


class FakeCompleted:
    def __init__(self, returncode, stdout=""):
        self.returncode = returncode
        self.stdout = stdout


def test_returns_token_when_item_exists(monkeypatch):
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return FakeCompleted(0, "tok3n-value\n")

    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(keychain.shutil, "which", lambda name: "/usr/bin/security")
    monkeypatch.setattr(subprocess, "run", fake_run)
    assert keychain.get_discord_bot_token() == "tok3n-value"
    # The command must target the dedicated service item, read-only (-w).
    (cmd,) = calls
    assert cmd[:2] == ["security", "find-generic-password"]
    assert "colfin-discord-bot" in cmd
    assert "-w" in cmd


def test_returns_none_when_item_missing(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(keychain.shutil, "which", lambda name: "/usr/bin/security")
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: FakeCompleted(44))
    assert keychain.get_discord_bot_token() is None


def test_returns_none_on_non_darwin(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("security must not be invoked off macOS")

    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(subprocess, "run", boom)
    assert keychain.get_discord_bot_token() is None


def test_returns_none_when_security_binary_missing(monkeypatch):
    def boom(*a, **k):
        # AssertionError, not OSError: the which() guard must prevent the call
        # (an OSError would be swallowed by get_discord_bot_token itself).
        raise AssertionError("subprocess must not run when 'security' is missing")

    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(keychain.shutil, "which", lambda name: None)
    monkeypatch.setattr(subprocess, "run", boom)
    assert keychain.get_discord_bot_token() is None


def test_returns_none_on_empty_stdout(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(keychain.shutil, "which", lambda name: "/usr/bin/security")
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: FakeCompleted(0, "\n"))
    assert keychain.get_discord_bot_token() is None
