"""Local VLM runtime: mlx-community/gemma-4-e4b-it-8bit served by mlx_vlm.server.

The model is hosted out-of-process by ``python -m mlx_vlm.server``, which
exposes an OpenAI-compatible HTTP API. Serving it once means the ~8.9 GB of
weights load a single time and are reused across harness runs instead of being
re-loaded on every invocation.

RAM sizing — verified against the HF repo: although the Hub metadata reports
~2.57B params, the safetensors shards on disk total ~8.9 GB — the E-series is a
MatFormer/elastic checkpoint larger than its effective param count suggests.
Expect ~10 GB resident for weights plus KV cache: 12 GB unified memory is
workable; 16 GB+ is comfortable. (Don't "correct" the size to match the HF
metadata.) The heavier ``gemma-12b`` alias roughly doubles these figures.

Nothing here touches the network or imports mlx at construction time, so the
parsers, orchestrator, and their tests stay fully offline — the server is
contacted lazily on the first ``generate()`` call.

Future optimisation (deliberately not wired): the server supports json_schema
structured output, which could replace the orchestrator's defensive fenced-JSON
parsing. Left out of scope — the existing parser + nag-retry is tested.
"""

import base64
import logging
import subprocess
import sys
import time
from pathlib import Path

import httpx

from colfin_harness.config import Settings, settings as default_settings

logger = logging.getLogger(__name__)


class MLXServerError(RuntimeError):
    """The mlx_vlm.server could not be reached or started."""


def _data_uri(image: str | Path) -> str:
    """Encode a screenshot PNG as a base64 data URI for the chat payload."""
    encoded = base64.b64encode(Path(image).read_bytes()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


class MLXServerManager:
    """Ensures a local mlx_vlm.server is up for the configured model.

    Reuses a healthy server it finds (and never stops one it did not start);
    spawns ``python -m mlx_vlm.server`` only when none is running.
    """

    def __init__(self, config: Settings | None = None):
        self.config = config or default_settings
        self._proc: subprocess.Popen | None = None  # set only if we spawned it
        self._ready = False

    @property
    def base_url(self) -> str:
        return self.config.model_server_base_url

    def _is_up(self) -> bool:
        """True when an OpenAI-style server answers /v1/models with a model list.
        Validating the JSON shape (not just that the socket answers) keeps an
        unrelated process on the port from being mistaken for our server."""
        try:
            resp = httpx.get(f"{self.base_url}/v1/models", timeout=2.0)
        except httpx.HTTPError:
            return False
        if resp.status_code != 200:
            return False
        try:
            data = resp.json()
        except ValueError:
            return False
        if not isinstance(data, dict) or "data" not in data:
            return False
        ids = {m.get("id") for m in data.get("data", [])}
        if ids and self.config.model_id not in ids:
            logger.warning(
                "model server on %s serves %s, not %s", self.base_url, ids, self.config.model_id
            )
        return True

    def ensure_running(self) -> None:
        if self._ready:
            return
        if self._is_up():
            logger.info("Reusing model server at %s", self.base_url)
            self._ready = True
            return
        self._spawn()
        self._wait_ready()
        self._ready = True

    def _spawn(self) -> None:
        logger.info(
            "Starting mlx_vlm.server for %s on %s (first run downloads and loads the weights)…",
            self.config.model_id,
            self.base_url,
        )
        # sys.executable (not bare "python") so the server runs in this venv,
        # where the Apple-only mlx-vlm dependency is installed.
        self._proc = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "mlx_vlm.server",
                "--model",
                self.config.model_id,
                "--host",
                self.config.model_server_host,
                "--port",
                str(self.config.model_server_port),
            ]
        )

    def _wait_ready(self) -> None:
        deadline = time.monotonic() + self.config.model_server_startup_timeout_s
        while time.monotonic() < deadline:
            if self._proc is not None and self._proc.poll() is not None:
                raise MLXServerError(
                    f"mlx_vlm.server exited early (code {self._proc.returncode}); "
                    "is mlx-vlm installed in this interpreter? (uv sync)"
                )
            if self._is_up():
                logger.info("Model server ready at %s", self.base_url)
                return
            time.sleep(2.0)
        self.stop()
        raise MLXServerError(
            f"mlx_vlm.server did not become ready within "
            f"{self.config.model_server_startup_timeout_s:.0f}s"
        )

    def stop(self) -> None:
        """Terminate the server only if we spawned it; a reused server is left
        running so it stays warm for the next harness run."""
        if self._proc is None:
            return
        self._proc.terminate()
        try:
            self._proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self._proc.kill()
        self._proc = None
        self._ready = False


class VLMRuntime:
    """Posts image-text chat-completion requests to the local mlx_vlm.server.

    Keeps the ``generate(prompt, images=[])`` signature the orchestrator's VLM
    Protocol expects, so the tool-calling loop and its tests are unaffected.
    """

    def __init__(self, config: Settings | None = None, server: MLXServerManager | None = None):
        self.config = config or default_settings
        self.model_id = self.config.model_id
        self._server = server or MLXServerManager(self.config)

    def ensure_server(self) -> None:
        """Eagerly bring the server up (used before the REPL so a cold load
        doesn't surprise the first question)."""
        self._server.ensure_running()

    def stop_server(self) -> None:
        self._server.stop()

    def generate(
        self,
        prompt: str,
        images: list[str | Path] | None = None,
        max_tokens: int = 1024,
        temperature: float = 0.0,
    ) -> str:
        """Run one image-text-to-text generation and return the text."""
        self._server.ensure_running()
        content: list[dict] = [{"type": "text", "text": prompt}]
        for image in images or []:
            content.append({"type": "image_url", "image_url": {"url": _data_uri(image)}})
        payload = {
            "model": self.model_id,
            "messages": [{"role": "user", "content": content}],
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        resp = httpx.post(
            f"{self.base_url}/v1/chat/completions",
            json=payload,
            timeout=self.config.model_request_timeout_s,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]

    @property
    def base_url(self) -> str:
        return self.config.model_server_base_url
