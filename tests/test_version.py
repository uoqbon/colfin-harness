"""``__version__`` must track the packaged version, not a hand-edited literal.

Regression guard: the literal previously sat at 0.1.0 for three releases while
pyproject.toml moved on. Deriving it from distribution metadata keeps the two
in lockstep; this test fails if that wiring breaks.
"""

from importlib.metadata import version

import colfin_harness


def test_dunder_version_matches_installed_metadata():
    assert colfin_harness.__version__ == version("colfin-harness")


def test_dunder_version_is_not_the_stale_literal():
    # The old drift symptom: a real release with __version__ frozen at 0.1.0.
    assert colfin_harness.__version__ != "0.1.0"
