"""Conversational history threading in the orchestrator. The no-history path
must stay byte-for-byte identical to the pre-refactor prompt."""

import json

from colfin_harness.orchestrator import Orchestrator, Turn
from colfin_harness.orchestrator.tools import Tool, ToolRegistry


class ScriptedVLM:
    def __init__(self, replies):
        self.replies = list(replies)
        self.prompts = []

    def generate(self, prompt, images=None, **kwargs):
        self.prompts.append(prompt)
        return self.replies.pop(0)


def _registry():
    registry = ToolRegistry()
    registry.register(Tool("noop", "no-op", {}, lambda: "ok"))
    return registry


def _final(answer):
    return f"```json\n{json.dumps({'final_answer': answer})}\n```"


def test_no_history_omits_conversation_block():
    vlm = ScriptedVLM([_final("done")])
    Orchestrator(vlm, _registry()).run("the task")
    assert "CONVERSATION SO FAR" not in vlm.prompts[0]
    assert "TASK: the task" in vlm.prompts[0]


def test_empty_history_omits_conversation_block():
    vlm = ScriptedVLM([_final("done")])
    Orchestrator(vlm, _registry()).run("t", history=[])
    assert "CONVERSATION SO FAR" not in vlm.prompts[0]


def test_history_injected_before_task():
    vlm = ScriptedVLM([_final("done")])
    Orchestrator(vlm, _registry()).run(
        "new task", history=[Turn("earlier q", "earlier a")]
    )
    prompt = vlm.prompts[0]
    assert "CONVERSATION SO FAR:" in prompt
    assert "Q: earlier q" in prompt
    assert "A: earlier a" in prompt
    assert prompt.index("CONVERSATION SO FAR:") < prompt.index("TASK: new task")
