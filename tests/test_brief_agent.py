"""
Tests for the conversational brief agent (T3).

The LLM is mocked: we patch get_llm in the brief_agent module so .chat() returns
canned JSON. interpret() must parse it into BriefActions and degrade to [noop]
on malformed output.
"""
import json
from unittest.mock import patch, MagicMock

import pytest

from packages.clips.curation.brief_models import BriefCandidate, BriefAction


def _candidates():
    return [
        BriefCandidate(id=1, start_time=100.0, end_time=140.0, title="Hook sobre IA",
                       summary="s", reasoning="", score=85.0, critic_approved=True,
                       above_threshold=True, selected=True, origin="curation"),
        BriefCandidate(id=2, start_time=300.0, end_time=340.0, title="Debate político",
                       summary="s", reasoning="", score=71.0, critic_approved=True,
                       above_threshold=True, selected=True, origin="curation"),
    ]


def _agent_with_llm_returning(raw):
    """Build a BriefAgent whose LLM .chat() returns `raw`, capturing the call."""
    fake_llm = MagicMock()
    fake_llm.chat.return_value = raw
    with patch("packages.clips.curation.agents.brief_agent.get_llm", return_value=fake_llm):
        from packages.clips.curation.agents.brief_agent import BriefAgent
        agent = BriefAgent()
    return agent, fake_llm


def test_interpret_parses_actions_from_llm_json():
    raw = json.dumps({"actions": [{"type": "drop", "targets": [2]}]})
    agent, _ = _agent_with_llm_returning(raw)
    actions = agent.interpret("quita el debate político", _candidates())
    assert len(actions) == 1
    assert isinstance(actions[0], BriefAction)
    assert actions[0].type == "drop"
    assert actions[0].targets == [2]


def test_interpret_multiple_actions_in_one_message():
    raw = json.dumps({"actions": [
        {"type": "drop", "targets": [2]},
        {"type": "reorder", "by": "controversy"},
    ]})
    agent, _ = _agent_with_llm_returning(raw)
    actions = agent.interpret("quita el 2 y ordena por polémica", _candidates())
    assert [a.type for a in actions] == ["drop", "reorder"]


def test_interpret_malformed_json_returns_noop():
    agent, _ = _agent_with_llm_returning("lo siento, no es JSON")
    actions = agent.interpret("haz algo raro", _candidates())
    assert len(actions) == 1
    assert actions[0].type == "noop"


def test_interpret_handles_json_in_code_fence():
    raw = "```json\n" + json.dumps({"actions": [{"type": "rescue", "targets": [2]}]}) + "\n```"
    agent, _ = _agent_with_llm_returning(raw)
    actions = agent.interpret("rescata el 2", _candidates())
    assert actions[0].type == "rescue" and actions[0].targets == [2]


def test_prompt_includes_candidates_and_action_catalog():
    agent, fake_llm = _agent_with_llm_returning(json.dumps({"actions": []}))
    agent.interpret("hola", _candidates())
    # Inspect what was sent to the LLM
    _, kwargs = fake_llm.chat.call_args
    sent = (kwargs.get("system_prompt", "") + " " + kwargs.get("user_message", ""))
    assert "Hook sobre IA" in sent and "Debate político" in sent  # candidates present
    for action_type in ("drop", "rescue", "reorder", "adjust_times", "find_new"):
        assert action_type in sent  # action catalog present
