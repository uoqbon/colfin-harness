"""mlx_vlm.server client — payload building, response parsing, reuse path.

Fully offline: the httpx calls and subprocess.Popen are monkeypatched, so no
server is started and no network is touched.
"""

import base64

from colfin_harness.model import runtime as runtime_mod
from colfin_harness.model.runtime import MLXServerManager, VLMRuntime


class _StubServer:
    def __init__(self):
        self.ensured = 0

    def ensure_running(self):
        self.ensured += 1

    def stop(self):
        pass


class _FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


def test_generate_builds_text_only_payload(monkeypatch):
    captured = {}

    def fake_post(url, json, timeout):
        captured.update(url=url, json=json, timeout=timeout)
        return _FakeResponse({"choices": [{"message": {"content": "hello"}}]})

    monkeypatch.setattr(runtime_mod.httpx, "post", fake_post)

    server = _StubServer()
    out = VLMRuntime(server=server).generate("hi there", max_tokens=42)

    assert out == "hello"
    assert server.ensured == 1  # the server is ensured before the request
    assert captured["url"].endswith("/v1/chat/completions")
    body = captured["json"]
    assert body["max_tokens"] == 42
    msg = body["messages"][0]
    assert msg["role"] == "user"
    assert msg["content"] == [{"type": "text", "text": "hi there"}]


def test_generate_encodes_images_as_data_uri(monkeypatch, tmp_path):
    png = tmp_path / "shot.png"
    png.write_bytes(b"\x89PNG\r\n")
    captured = {}

    def fake_post(url, json, timeout):
        captured["json"] = json
        return _FakeResponse({"choices": [{"message": {"content": "ok"}}]})

    monkeypatch.setattr(runtime_mod.httpx, "post", fake_post)

    VLMRuntime(server=_StubServer()).generate("look", images=[png])

    content = captured["json"]["messages"][0]["content"]
    assert content[0] == {"type": "text", "text": "look"}
    image = content[1]
    assert image["type"] == "image_url"
    expected = base64.b64encode(b"\x89PNG\r\n").decode("ascii")
    assert image["image_url"]["url"] == f"data:image/png;base64,{expected}"


def test_ensure_running_reuses_healthy_server(monkeypatch):
    mgr = MLXServerManager()
    healthy = _FakeResponse({"data": [{"id": mgr.config.model_id}]})
    monkeypatch.setattr(runtime_mod.httpx, "get", lambda url, timeout: healthy)

    def no_spawn(*a, **k):
        raise AssertionError("must not spawn when a healthy server is already up")

    monkeypatch.setattr(runtime_mod.subprocess, "Popen", no_spawn)

    mgr.ensure_running()
    assert mgr._proc is None  # reused, never spawned


def test_is_up_false_when_unreachable(monkeypatch):
    def refuse(url, timeout):
        raise runtime_mod.httpx.ConnectError("nope")

    monkeypatch.setattr(runtime_mod.httpx, "get", refuse)
    assert MLXServerManager()._is_up() is False
