import json

import pytest

from colfin_harness.exceptions import OrchestrationError, ProtocolError
from colfin_harness.orchestrator.loop import Orchestrator, extract_tool_call
from colfin_harness.orchestrator.tools import Tool, ToolRegistry

# -- protocol parsing ---------------------------------------------------------


def test_extracts_fenced_json():
    reply = 'Sure.\n```json\n{"thought": "t", "tool": "get_quote", "args": {"symbol": "TEL"}}\n```'
    call = extract_tool_call(reply)
    assert call["tool"] == "get_quote"
    assert call["args"] == {"symbol": "TEL"}


def test_extracts_fence_without_language_tag():
    reply = '```\n{"thought": "t", "final_answer": "done"}\n```'
    assert extract_tool_call(reply)["final_answer"] == "done"


def test_extracts_bare_json_embedded_in_prose():
    reply = 'I will call a tool now: {"tool": "get_portfolio", "args": {}} — waiting.'
    assert extract_tool_call(reply)["tool"] == "get_portfolio"


def test_skips_irrelevant_json_objects():
    reply = '{"note": "not a call"} then {"tool": "get_quote", "args": {}}'
    assert extract_tool_call(reply)["tool"] == "get_quote"


def test_no_json_raises_protocol_error():
    with pytest.raises(ProtocolError):
        extract_tool_call("I would like to check the quote for TEL.")


# -- loop behavior ------------------------------------------------------------


class ScriptedVLM:
    def __init__(self, replies):
        self.replies = list(replies)
        self.prompts = []

    def generate(self, prompt, images=None, **kwargs):
        self.prompts.append(prompt)
        return self.replies.pop(0)


def _registry(calls):
    registry = ToolRegistry()

    def echo(text: str) -> str:
        calls.append(text)
        return f"echo: {text}"

    registry.register(Tool("echo", "Echo the text back.", {"text": "text to echo"}, echo))
    return registry


def _fenced(obj) -> str:
    return f"```json\n{json.dumps(obj)}\n```"


def test_loop_retries_malformed_then_runs_tool_then_finishes():
    calls = []
    vlm = ScriptedVLM(
        [
            "let me think about this without any JSON…",  # malformed → retried
            _fenced({"thought": "call", "tool": "echo", "args": {"text": "hi"}}),
            _fenced({"thought": "done", "final_answer": "the echo said hi"}),
        ]
    )
    result = Orchestrator(vlm, _registry(calls)).run("test task")

    assert result == "the echo said hi"
    assert calls == ["hi"]
    assert "PROTOCOL ERROR" in vlm.prompts[1]  # nag fed back on retry
    assert "OBSERVATION: echo: hi" in vlm.prompts[2]


def test_loop_reports_unknown_tool_as_observation():
    vlm = ScriptedVLM(
        [
            _fenced({"thought": "?", "tool": "nope", "args": {}}),
            _fenced({"thought": "ok", "final_answer": "recovered"}),
        ]
    )
    assert Orchestrator(vlm, _registry([])).run("task") == "recovered"
    assert "ERROR: unknown tool 'nope'" in vlm.prompts[1]


def test_loop_reports_bad_args_as_observation():
    vlm = ScriptedVLM(
        [
            _fenced({"thought": "?", "tool": "echo", "args": {"wrong": 1}}),
            _fenced({"thought": "ok", "final_answer": "recovered"}),
        ]
    )
    assert Orchestrator(vlm, _registry([])).run("task") == "recovered"
    assert "ERROR: bad arguments for echo" in vlm.prompts[1]


def test_loop_gives_up_after_persistent_protocol_failures():
    vlm = ScriptedVLM(["nope", "still nope", "nada"])
    with pytest.raises(OrchestrationError):
        Orchestrator(vlm, _registry([]), max_parse_retries=3).run("task")
