"""Credential parsing/prompting — pure, offline, no real stdin."""

import getpass

import pytest

from colfin_harness.credentials import Credentials, prompt_credentials, validate_user_id


def test_validate_user_id_accepts_canonical_and_trims():
    assert validate_user_id("1234-5678") == "1234-5678"
    assert validate_user_id("  1234-5678  ") == "1234-5678"


@pytest.mark.parametrize(
    "bad",
    ["12345678", "123-4567", "1234-567", "12345-678", "abcd-efgh", "1234_5678", "", "   "],
)
def test_validate_user_id_rejects(bad):
    with pytest.raises(ValueError):
        validate_user_id(bad)


def test_user_parts_splits_on_dash():
    assert Credentials("1234-5678", "secret").user_parts() == ("1234", "5678")


def test_repr_masks_password():
    text = repr(Credentials("1234-5678", "secret"))
    assert "secret" not in text
    assert "***" in text
    assert "1234-5678" in text


def test_clear_drops_password():
    creds = Credentials("1234-5678", "secret")
    creds.clear()
    assert creds.password == ""
    assert "<cleared>" in repr(creds)


def test_prompt_uses_valid_arg_and_getpass(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda *a: pytest.fail("must not prompt for a valid user id"))
    monkeypatch.setattr(getpass, "getpass", lambda *a, **k: "pw")
    creds = prompt_credentials("1234-5678")
    assert creds.user_id == "1234-5678"
    assert creds.password == "pw"


def test_prompt_reprompts_user_id_until_valid(monkeypatch):
    answers = iter(["nope", "12345678", "1234-5678"])
    monkeypatch.setattr("builtins.input", lambda *a: next(answers))
    monkeypatch.setattr(getpass, "getpass", lambda *a, **k: "pw")
    creds = prompt_credentials(None)
    assert creds.user_id == "1234-5678"
    assert creds.password == "pw"


def test_prompt_falls_back_to_input_when_arg_invalid(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda *a: "1234-5678")
    monkeypatch.setattr(getpass, "getpass", lambda *a, **k: "pw")
    creds = prompt_credentials("not-valid")
    assert creds.user_id == "1234-5678"
