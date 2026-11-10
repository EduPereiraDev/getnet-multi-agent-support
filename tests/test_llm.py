"""LLM layer tests: offline client, prompt loading and the Anthropic tool loop with a fake SDK."""

import json
from types import SimpleNamespace

import pytest
from pydantic import BaseModel

from app.config import get_settings
from app.llm.client import AnthropicLLM, LLMUnavailable, OfflineLLM, get_llm, load_prompt


def _tool_use(id_: str, name: str, input_: dict) -> SimpleNamespace:
    return SimpleNamespace(type="tool_use", id=id_, name=name, input=input_)


def _text(text: str) -> SimpleNamespace:
    return SimpleNamespace(type="text", text=text)


class FakeMessages:
    def __init__(self, responses: list[SimpleNamespace]) -> None:
        self.responses = list(responses)
        self.calls: list[dict] = []

    def create(self, **kwargs):
        # Snapshot messages: the client mutates the same list across iterations.
        self.calls.append({**kwargs, "messages": list(kwargs["messages"])})
        return self.responses.pop(0)

    def parse(self, **kwargs):
        self.calls.append(kwargs)
        return self.responses.pop(0)


def _llm(responses: list[SimpleNamespace]) -> tuple[AnthropicLLM, FakeMessages]:
    messages = FakeMessages(responses)
    return AnthropicLLM(client=SimpleNamespace(messages=messages)), messages


@pytest.fixture
def offline(monkeypatch):
    monkeypatch.setenv("LLM_MODE", "offline")
    get_settings.cache_clear()
    get_llm.cache_clear()
    yield
    get_settings.cache_clear()
    get_llm.cache_clear()


def test_offline_llm_raises(offline):
    llm = get_llm()
    assert isinstance(llm, OfflineLLM) and llm.mode == "offline"
    with pytest.raises(LLMUnavailable):
        llm.structured("s", "u", BaseModel)
    with pytest.raises(LLMUnavailable):
        llm.run_tools("s", "u", [], lambda name, args: {})


@pytest.mark.parametrize("name", ["router", "knowledge", "support", "escalation", "composer"])
def test_load_prompt(name):
    text = load_prompt(name)
    assert len(text) > 200
    assert "untrusted" in text.lower()


def test_run_tools_loop():
    llm, fake = _llm(
        [
            SimpleNamespace(
                stop_reason="tool_use",
                content=[
                    _text("Checking."),
                    _tool_use("tu_1", "get_terminal_status", {"user_id": "c1"}),
                    _tool_use("tu_2", "get_settlement_schedule", {"user_id": "c1"}),
                ],
            ),
            SimpleNamespace(
                stop_reason="end_turn", content=[_text("Terminal offline."), _text("Deposit tomorrow.")]
            ),
        ]
    )
    executed: list[tuple[str, dict]] = []

    def execute(name: str, args: dict) -> dict:
        executed.append((name, args))
        return {"ok": True, "status": "offline"}

    text, calls = llm.run_tools("sys", "my machine won't connect", [{"name": "x"}], execute)

    assert executed == [
        ("get_terminal_status", {"user_id": "c1"}),
        ("get_settlement_schedule", {"user_id": "c1"}),
    ]
    assert text == "Terminal offline.\nDeposit tomorrow."
    assert [(c.tool, c.ok, c.args) for c in calls] == [
        ("get_terminal_status", True, {"user_id": "c1"}),
        ("get_settlement_schedule", True, {"user_id": "c1"}),
    ]
    assert len(fake.calls) == 2
    first = fake.calls[0]
    assert first["tool_choice"] == {"type": "auto"} and first["system"] == "sys"
    assert not {"temperature", "top_p", "top_k", "thinking"} & first.keys()

    second = fake.calls[1]["messages"]
    assert [m["role"] for m in second] == ["user", "assistant", "user"]
    assert second[1]["content"] is not None and len(second[1]["content"]) == 3
    results = second[2]["content"]
    assert [r["tool_use_id"] for r in results] == ["tu_1", "tu_2"]
    assert all(r["type"] == "tool_result" and r["is_error"] is False for r in results)
    assert json.loads(results[0]["content"]) == {"ok": True, "status": "offline"}


def test_run_tools_executor_error():
    llm, fake = _llm(
        [
            SimpleNamespace(
                stop_reason="tool_use", content=[_tool_use("tu_1", "get_customer_profile", {"user_id": "zz"})]
            ),
            SimpleNamespace(stop_reason="end_turn", content=[_text("Could not find your account.")]),
        ]
    )

    def execute(name: str, args: dict) -> dict:
        raise LookupError("user_id 'zz' not found")

    text, calls = llm.run_tools("sys", "hi", [], execute)

    assert text == "Could not find your account."
    assert calls[0].ok is False and "not found" in calls[0].error
    result = fake.calls[1]["messages"][-1]["content"][0]
    assert result["is_error"] is True
    assert json.loads(result["content"])["ok"] is False


def test_run_tools_respects_budget(monkeypatch):
    monkeypatch.setattr(get_settings(), "llm_max_tool_iterations", 2)
    looping = [
        SimpleNamespace(
            stop_reason="tool_use", content=[_text(f"step {i}"), _tool_use(f"tu_{i}", "web_search", {"q": i})]
        )
        for i in range(5)
    ]
    llm, fake = _llm(looping)

    with pytest.raises(LLMUnavailable, match="incomplete"):
        llm.run_tools("sys", "hi", [], lambda name, args: {"ok": True})

    assert len(fake.calls) == 3  # initial request + 2 tool iterations, then give up (no partial answer)


def test_run_tools_refusal():
    llm, _ = _llm([SimpleNamespace(stop_reason="refusal", content=[])])
    with pytest.raises(LLMUnavailable):
        llm.run_tools("sys", "hi", [], lambda name, args: {})


class Plan(BaseModel):
    label: str


def test_structured():
    llm, fake = _llm([SimpleNamespace(parsed_output=Plan(label="knowledge"), stop_reason="end_turn")])

    result = llm.structured("sys", "Get Smart fees?", Plan, model="claude-haiku-5-5")

    assert result == Plan(label="knowledge")
    call = fake.calls[0]
    assert call["output_format"] is Plan and call["model"] == "claude-haiku-5-5"
    assert call["messages"] == [{"role": "user", "content": "Get Smart fees?"}]


def test_structured_refusal():
    llm, _ = _llm([SimpleNamespace(parsed_output=None, stop_reason="refusal")])
    with pytest.raises(LLMUnavailable):
        llm.structured("sys", "u", Plan)
