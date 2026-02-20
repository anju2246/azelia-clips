import pytest
import json
from unittest.mock import patch, MagicMock
from dataclasses import dataclass
from typing import List
from packages.clips.curation.curator_v2 import MultiAgentCurator, CuratedClipV2, ViralityScoreV2

# Simple Mock Objects to replace the transcription structures normally passed from Whisper
@dataclass
class MockSegment:
    start: float
    end: float
    text: str
    speaker: str = "A"

@dataclass
class MockTranscript:
    segments: List[MockSegment]
    language: str = "en"
    duration: float = 60.0
    source_file: str = "mock.mp4"

@pytest.fixture
@patch('packages.clips.curation.curator_v2.get_llm')
def curator(mock_get_llm):
    # Instantiate without external API calls by mocking them later
    mock_get_llm.return_value = MagicMock()
    return MultiAgentCurator(temperature=0.0)

@pytest.fixture
def sample_transcript():
    return MockTranscript(
        segments=[
            MockSegment(start=0.0, end=10.0, text="Intro to the podcast."),
            MockSegment(start=10.0, end=40.0, text="A really crazy story about dropping out of college to build an AI."),
            MockSegment(start=40.0, end=50.0, text="The end result was amazing."),
            MockSegment(start=50.0, end=60.0, text="Outro and say goodbye.")
        ],
        duration=60.0
    )

def test_parse_json_robustness(curator):
    """Ensure the JSON parsing handles markdown blocks and newlines cleanly."""
    valid_json = '```json\n{"candidates": [{"start": 10, "end": 40}]}\n```'
    parsed = curator._parse_json(valid_json)
    assert "candidates" in parsed
    assert len(parsed["candidates"]) == 1

    # Heuristic test without markdown blocks
    raw_json = '{"approved": [{"start": 10, "end": 40}]}'
    parsed_raw = curator._parse_json(raw_json)
    assert "approved" in parsed_raw

def test_deduplicate_clips(curator):
    """Ensure clips with overlapping timestamps accurately deduplicate, keeping the highest score."""
    clip1 = CuratedClipV2(
        start_time=10.0, end_time=40.0, title="A", summary="A",
        virality_score=ViralityScoreV2(hook_strength=5, optimal_duration=5), # Total 10
        category="insight"
    )
    clip2 = CuratedClipV2(
        start_time=15.0, end_time=45.0, title="B", summary="B",
        virality_score=ViralityScoreV2(hook_strength=10, optimal_duration=10), # Total 20
        category="insight"
    )

    # 10 to 40 vs 15 to 45 implies a 25s overlap. 25s / 30s duration > 0.5 threshold
    unique = curator._deduplicate_clips([clip1, clip2], overlap_threshold=0.5)
    
    assert len(unique) == 1
    # Should keep clip2 because its total score (20) > clip1 (10)
    assert unique[0].title == "B"

def test_clip_duration_validation(curator):
    """Verify that too short/long clips are properly flagged for manual review or invalidated."""
    # Valid
    assert curator._validate_clip_duration(10, 50, min_duration=30, max_duration=60) == 'valid'
    # Too short - always discard unless super viral
    assert curator._validate_clip_duration(10, 20, min_duration=30, max_duration=60, virality_score=10) == 'invalid'
    # Short but viral - pending
    assert curator._validate_clip_duration(10, 25, min_duration=30, max_duration=60, virality_score=60) == 'pending'
    # Too long - pending
    assert curator._validate_clip_duration(10, 80, min_duration=30, max_duration=60) == 'pending'
    # Excessively long (> 3 mins)
    assert curator._validate_clip_duration(10, 200, min_duration=30, max_duration=60) == 'invalid'

@patch.object(MultiAgentCurator, '_call_agent')
@patch.object(MultiAgentCurator, '_extract_signals_summary', return_value="Mocked signals")
@patch.object(MultiAgentCurator, '_extract_clip_text', return_value="Mocked clip text", create=True)
def test_full_curation_pipeline_mocked(mock_clip_text, mock_signals, mock_call_agent, curator, sample_transcript):
    """Test the Multi-Agent (Finder -> Critic -> Ranker) pipeline completely isolated from LLM requests."""
    
    # Configure sequential network mocks for Finder, Critic, Ranker
    def mock_llm_chain(system, user, agent_name, **kwargs):
        if "FINDER" in agent_name:
            return json.dumps({
                "candidates": [
                    {"start": 10.0, "end": 40.0, "reasoning": "Great story"}
                ]
            })
        elif "CRITIC" in agent_name:
            return json.dumps({
                "approved": [
                    {"start": 10.0, "end": 40.0, "reasoning": "Approved for high energy"}
                ]
            })
        elif "RANKER" in agent_name:
            return json.dumps({
                "ranked_clips": [{
                    "start_time": 10.0, 
                    "end_time": 40.0, 
                    "title": "College Dropout to AI Builder",
                    "summary": "Crazy story about AI",
                    "category": "story",
                    "virality_score": {
                        "hook_strength": 9,
                        "storytelling": 10,
                        "optimal_duration": 8
                    }
                }]
            })
        elif "CAPTION" in agent_name:
            return json.dumps({
                "caption": "You won't believe this story! 🤯",
                "hashtags": ["#AI", "#Story"]
            })
        return "{}"

    mock_call_agent.side_effect = mock_llm_chain

    # Force execution of chunked processing via min_duration overrides to catch all network nodes
    results = curator.curate_chunked(
        transcript=sample_transcript,
        top_n=1,
        min_duration=30,
        max_duration=60,
        episode_number=1, # Triggers the CAPTION network call
        guest_name="Mock Guest"
    )

    assert len(results) == 1
    clip = results[0]
    
    assert clip.title == "College Dropout to AI Builder"
    # Duration = 40.0 - 10.0 = 30.0s (valid, neither pending nor invalid)
    assert clip.pending_review is False
    assert clip.virality_score.storytelling == 10
    
    # Check that Captions triggered properly since episode_number > 0
    assert clip.social_caption == "You won't believe this story! 🤯"
    assert "#AI" in clip.caption_hashtags
