"""Model selection: the Gemma-on-MLX lock, applied identically at the alias
resolver, the ``Settings`` field validator (default / env var / construction),
and the ``--model`` CLI override. Fully offline — only string validation and
config construction; no server spawn, no weight download, no network."""

import pytest

from colfin_harness import __main__ as cli
from colfin_harness.config import (
    DEFAULT_MODEL_ID,
    GEMMA_MLX_MODELS,
    Settings,
    resolve_model_id,
)

LOCK_MSG = "locked to the Google Gemma family"


# --- resolve_model_id: alias resolution + the Gemma+MLX guard ----------------

def test_alias_resolves_to_full_repo():
    assert resolve_model_id("gemma-12b") == DEFAULT_MODEL_ID


def test_default_is_a_registered_alias_target():
    # The shipped default must be reachable by an alias, so --list-models can
    # tag it and callers aren't forced to type the full repo to get it.
    assert DEFAULT_MODEL_ID in GEMMA_MLX_MODELS.values()


def test_resolver_trims_surrounding_whitespace():
    assert resolve_model_id("  gemma-12b  ") == DEFAULT_MODEL_ID


@pytest.mark.parametrize(
    "repo",
    [
        "mlx-community/gemma-4-12B-it-8bit",  # the default
        "mlx-community/gemma-4-12B-it-4bit",  # lighter quant
        "mlx-community/gemma-4-31b-it-8bit",  # larger sibling
        "mlx-community/gemma-4-e4b-it-4bit",  # small edge variant
        "someuser/gemma-3-12b-it-mlx",        # mlx in the name, not the org
    ],
)
def test_guard_accepts_any_gemma_on_mlx_repo(repo):
    # Hybrid lock: a full repo id need not be a registered alias, only Gemma+MLX.
    assert resolve_model_id(repo) == repo


@pytest.mark.parametrize(
    "repo",
    [
        "google/gemma-4-12B-it",                   # Gemma, but base (not MLX)
        "mlx-community/Llama-3-8B-Instruct-4bit",  # MLX, but not Gemma
        "mlx-community/Qwen2-VL-7B-4bit",          # neither
        "gpt-4o",                                  # nonsense
        "gemma-12b-typo",                          # unregistered + no mlx marker
    ],
)
def test_guard_rejects_outside_the_box(repo):
    with pytest.raises(ValueError, match=LOCK_MSG):
        resolve_model_id(repo)


# --- Settings field validator: default / construction / env var are locked ---

def test_settings_default_is_valid():
    assert Settings().model_id == DEFAULT_MODEL_ID


def test_settings_resolves_alias_on_construction():
    assert Settings(model_id="gemma-12b").model_id == DEFAULT_MODEL_ID


def test_settings_accepts_full_gemma_mlx_repo():
    repo = "mlx-community/gemma-4-31b-it-8bit"
    assert Settings(model_id=repo).model_id == repo


def test_settings_rejects_non_gemma_mlx():
    # The validator raises a pydantic ValidationError, which subclasses ValueError.
    with pytest.raises(ValueError, match=LOCK_MSG):
        Settings(model_id="google/gemma-4-12B-it")


def test_env_var_override_is_locked(monkeypatch):
    monkeypatch.setenv("COLFIN_MODEL_ID", "mlx-community/Llama-3-8B-4bit")
    with pytest.raises(ValueError, match=LOCK_MSG):
        Settings()


def test_env_var_alias_resolves(monkeypatch):
    monkeypatch.setenv("COLFIN_MODEL_ID", "gemma-12b")
    assert Settings().model_id == DEFAULT_MODEL_ID


# --- resolve_settings: the --model CLI override path -------------------------

def test_resolve_settings_no_overrides_returns_base():
    assert cli.resolve_settings(None, None) is cli.default_settings


def test_resolve_settings_applies_model_alias():
    resolved = cli.resolve_settings(None, "gemma-12b")
    assert resolved.model_id == DEFAULT_MODEL_ID
    assert resolved is not cli.default_settings  # a copy, base untouched
    assert cli.default_settings.model_id == DEFAULT_MODEL_ID


def test_resolve_settings_applies_full_repo():
    repo = "mlx-community/gemma-4-12B-it-4bit"
    assert cli.resolve_settings(None, repo).model_id == repo


def test_resolve_settings_rejects_bad_model():
    # model_copy skips validators, so resolve_settings must guard the value itself.
    with pytest.raises(ValueError, match=LOCK_MSG):
        cli.resolve_settings(None, "google/gemma-4-12B-it")


def test_resolve_settings_model_and_headless_compose():
    resolved = cli.resolve_settings(True, "mlx-community/gemma-4-31b-it-4bit")
    assert resolved.headless is True
    assert resolved.model_id == "mlx-community/gemma-4-31b-it-4bit"
