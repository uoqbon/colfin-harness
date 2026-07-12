"""Multi-agent harness for the COL Financial trading platform.

Read-only agents (quotes, portfolio) are fully implemented. Order entry is a
documented stub behind a hard human-confirmation guard — this package never
submits orders.
"""

from importlib.metadata import PackageNotFoundError, version

try:
    # Single source of truth is pyproject.toml; read it back from the
    # installed distribution metadata so __version__ can never drift from the
    # released version. (The project is always installed editable via uv.)
    __version__ = version("colfin-harness")
except PackageNotFoundError:  # running from a source tree with no dist metadata
    __version__ = "0.0.0+unknown"

del version, PackageNotFoundError
