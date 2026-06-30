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


def test_priority_message_yields_reorder_with_order():
    # The LLM (which sees the candidates) returns a semantic ordering as reorder.
    raw = json.dumps({"actions": [{"type": "reorder", "order": [2, 1]}]})
    agent, _ = _agent_with_llm_returning(raw)
    actions = agent.interpret("prioriza los polémicos", _candidates())
    assert len(actions) == 1
    assert actions[0].type == "reorder"
    assert actions[0].order == [2, 1]


def test_prompt_steers_prioritization_to_reorder_and_drops_recurate():
    agent, fake_llm = _agent_with_llm_returning(json.dumps({"actions": []}))
    agent.interpret("prioriza algo", _candidates())
    _, kwargs = fake_llm.chat.call_args
    system = kwargs.get("system_prompt", "")
    assert "recurate_focus" not in system  # deterministic re-rank retired
    assert "reorder" in system and "prioriz" in system.lower()  # steer priorities to reorder


def test_focus_id_scopes_prompt_to_current_clip():
    # In the one-by-one flow the UI tells the agent which clip is on screen, so
    # ambiguous feedback ("recórtalo", "quítalo") resolves to that clip.
    agent, fake_llm = _agent_with_llm_returning(json.dumps({"actions": []}))
    agent.interpret("recórtalo 5s", _candidates(), focus_id=2)
    _, kwargs = fake_llm.chat.call_args
    sent = kwargs.get("system_prompt", "") + " " + kwargs.get("user_message", "")
    assert "#2" in sent  # the focused clip is named
    assert "foco" in sent.lower()  # an explicit focus marker is present


def test_trim_to_text_in_catalog_and_parses():
    raw = json.dumps({"actions": [
        {"type": "trim_to_text", "id": 1, "keep_text": "esto es la parte buena"},
    ]})
    agent, fake_llm = _agent_with_llm_returning(raw)
    actions = agent.interpret("déjalo solo con esto: ...", _candidates(), focus_id=1)
    assert actions[0].type == "trim_to_text"
    assert actions[0].id == 1 and "parte buena" in actions[0].keep_text
    # the catalog + steering must be in the prompt
    _, kwargs = fake_llm.chat.call_args
    system = kwargs.get("system_prompt", "")
    assert "trim_to_text" in system
    assert "lo demás" in system.lower() or "lo demas" in system.lower()


def test_focus_steering_says_dont_touch_other_clips():
    agent, fake_llm = _agent_with_llm_returning(json.dumps({"actions": []}))
    agent.interpret("recórtalo y lo demás bórralo", _candidates(), focus_id=1)
    _, kwargs = fake_llm.chat.call_args
    sent = kwargs.get("system_prompt", "") + " " + kwargs.get("user_message", "")
    # the focused clip is named and other clips are protected unless named
    assert "#1" in sent
    assert "drop" in sent.lower()


def _candidates_with_transcript():
    cs = _candidates()
    cs[0].transcript = "esto es la parte buena del clip uno sobre inteligencia artificial"
    cs[1].transcript = "y este es el clip dos sobre el debate"
    return cs


def test_build_message_includes_focus_transcript():
    agent, fake_llm = _agent_with_llm_returning(json.dumps({"actions": []}))
    agent.interpret("recórtalo a esto", _candidates_with_transcript(), focus_id=1)
    _, kwargs = fake_llm.chat.call_args
    user_msg = kwargs.get("user_message", "")
    assert "Transcript del clip en foco" in user_msg
    assert "esto es la parte buena del clip uno" in user_msg
    # the OTHER clip's transcript must not be dumped
    assert "clip dos sobre el debate" not in user_msg


def test_build_message_no_focus_omits_transcript():
    agent, fake_llm = _agent_with_llm_returning(json.dumps({"actions": []}))
    agent.interpret("ordena por polémica", _candidates_with_transcript())
    _, kwargs = fake_llm.chat.call_args
    user_msg = kwargs.get("user_message", "")
    assert "Transcript del clip en foco" not in user_msg


def test_build_message_truncates_long_transcript():
    cs = _candidates_with_transcript()
    cs[0].transcript = "palabra " * 1000  # ~8000 chars
    agent, fake_llm = _agent_with_llm_returning(json.dumps({"actions": []}))
    agent.interpret("recórtalo", cs, focus_id=1)
    _, kwargs = fake_llm.chat.call_args
    user_msg = kwargs.get("user_message", "")
    assert "…" in user_msg
    # the focus transcript block must be bounded (not the full 8000 chars)
    assert len(user_msg) < 6000


def test_system_prompt_forbids_only_ranges_excuse():
    agent, fake_llm = _agent_with_llm_returning(json.dumps({"actions": []}))
    agent.interpret("recórtalo a esto", _candidates_with_transcript(), focus_id=1)
    _, kwargs = fake_llm.chat.call_args
    system = kwargs.get("system_prompt", "").lower()
    assert "solo conoz" in system or "solo conoc" in system  # explicitly names the forbidden excuse
    assert "rangos" in system


def test_focus_id_absent_keeps_global_prompt():
    # Without a focus the user message must not fabricate a specific focused clip
    # (the system prompt still explains the concept; the dynamic block does not).
    agent, fake_llm = _agent_with_llm_returning(json.dumps({"actions": []}))
    agent.interpret("ordena por polémica", _candidates())
    _, kwargs = fake_llm.chat.call_args
    user_msg = kwargs.get("user_message", "")
    assert "Clip en foco" not in user_msg
    assert "EN FOCO" not in user_msg
