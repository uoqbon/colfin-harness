"""ReAct-style tool-calling loop for a model without native function calling.

Protocol: every model turn must contain exactly one JSON object, ideally in a
```json fence, shaped as either

    {"thought": "...", "tool": "<name>", "args": {...}}
    {"thought": "...", "final_answer": "..."}

Parsing is defensive (fenced block first, then a balanced-brace scan) and
malformed turns are retried with the error fed back to the model.
"""

import json
import logging
from dataclasses import dataclass, field
from typing import Protocol

from colfin_harness.exceptions import OrchestrationError, ProtocolError
from colfin_harness.orchestrator.tools import ToolRegistry, ToolResult

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
You are a careful assistant for the COL Financial trading platform. You can
only read data; you can never place, modify, or submit orders — if asked to
trade, explain that order submission requires the human to confirm Step 2 of
the order wizard in their browser.

You have these tools:
{catalog}

Respond with EXACTLY ONE JSON object inside a ```json fence and nothing else.
To call a tool:
```json
{{"thought": "<why>", "tool": "<tool name>", "args": {{<arguments>}}}}
```
To finish:
```json
{{"thought": "<why>", "final_answer": "<answer for the user>"}}
```

Rules:
- One tool call per turn. Wait for the OBSERVATION before continuing.
- args must be a JSON object, {{}} if the tool takes none.
- If an observation reports an error, adjust and try again.
"""


class VLM(Protocol):
    def generate(self, prompt: str, images: list | None = None, **kwargs) -> str: ...


def _balanced_json_objects(text: str):
    """Yield decoded top-level {...} objects found anywhere in the text."""
    decoder = json.JSONDecoder()
    i = 0
    while (start := text.find("{", i)) != -1:
        try:
            obj, end = decoder.raw_decode(text[start:])
        except json.JSONDecodeError:
            i = start + 1
            continue
        if isinstance(obj, dict):
            yield obj
        i = start + end


def extract_tool_call(reply: str) -> dict:
    """Pull the protocol object out of a model reply."""
    candidates = []
    # Prefer fenced blocks; tolerate a missing language tag.
    for fence in ("```json", "```"):
        if fence in reply:
            for chunk in reply.split(fence)[1:]:
                body = chunk.split("```")[0]
                candidates.extend(_balanced_json_objects(body))
            break
    if not candidates:
        candidates = list(_balanced_json_objects(reply))
    for obj in candidates:
        if "final_answer" in obj or "tool" in obj:
            return obj
    raise ProtocolError(
        "reply contained no JSON object with a 'tool' or 'final_answer' key"
    )


@dataclass
class Step:
    call: dict
    observation: str = ""
    images: list[str] = field(default_factory=list)


@dataclass
class Turn:
    """One completed REPL exchange. Only the question and the final answer are
    carried into later turns — never the intra-turn ACTION/OBSERVATION steps,
    whose JSON observations and screenshots would quickly blow the context."""

    question: str
    answer: str


class Orchestrator:
    def __init__(
        self,
        vlm: VLM,
        registry: ToolRegistry,
        max_steps: int = 10,
        max_parse_retries: int = 3,
    ):
        self.vlm = vlm
        self.registry = registry
        self.max_steps = max_steps
        self.max_parse_retries = max_parse_retries

    # -- prompt assembly ------------------------------------------------------

    def _compose(
        self,
        task: str,
        steps: list[Step],
        protocol_nag: str | None,
        history: list[Turn] | None = None,
    ) -> str:
        parts = [SYSTEM_PROMPT.format(catalog=self.registry.render_catalog())]
        if history:
            convo = "\n".join(f"Q: {turn.question}\nA: {turn.answer}" for turn in history)
            parts.append(f"CONVERSATION SO FAR:\n{convo}")
        parts.append(f"TASK: {task}")
        for step in steps:
            parts.append(f"ACTION: {json.dumps(step.call)}")
            parts.append(f"OBSERVATION: {step.observation}")
        if protocol_nag:
            parts.append(f"PROTOCOL ERROR: {protocol_nag} Reply again with one valid JSON object.")
        return "\n\n".join(parts)

    # -- execution --------------------------------------------------------------

    def _next_call(
        self,
        task: str,
        steps: list[Step],
        images: list[str],
        history: list[Turn] | None = None,
    ) -> dict:
        nag = None
        for _ in range(self.max_parse_retries):
            reply = self.vlm.generate(
                self._compose(task, steps, nag, history), images=images or None
            )
            try:
                return extract_tool_call(reply)
            except ProtocolError as exc:
                logger.warning("unparseable model turn: %s", exc)
                nag = str(exc)
                images = []  # don't resend images on a retry
        raise OrchestrationError(
            f"model failed to produce a valid tool call in {self.max_parse_retries} attempts"
        )

    def _execute(self, call: dict) -> ToolResult:
        name = call.get("tool")
        tool = self.registry.get(name) if isinstance(name, str) else None
        if tool is None:
            return ToolResult(
                f"ERROR: unknown tool {name!r}. Available: {', '.join(self.registry.names())}"
            )
        args = call.get("args") or {}
        if not isinstance(args, dict):
            return ToolResult("ERROR: 'args' must be a JSON object")
        try:
            result = tool.fn(**args)
        except TypeError as exc:
            return ToolResult(f"ERROR: bad arguments for {name}: {exc}")
        except Exception as exc:  # surface tool failures to the model, keep looping
            return ToolResult(f"ERROR: {type(exc).__name__}: {exc}")
        return result if isinstance(result, ToolResult) else ToolResult(str(result))

    def run(self, task: str, history: list[Turn] | None = None) -> str:
        steps: list[Step] = []
        pending_images: list[str] = []
        for _ in range(self.max_steps):
            call = self._next_call(task, steps, pending_images, history)
            if "final_answer" in call:
                return str(call["final_answer"])
            result = self._execute(call)
            pending_images = result.images
            steps.append(Step(call=call, observation=result.text, images=result.images))
            logger.info("tool %s → %.120s", call.get("tool"), result.text)
        raise OrchestrationError(f"no final answer after {self.max_steps} steps")
