import pytest
import json
from unittest.mock import patch, MagicMock
from dataclasses import dataclass
from typing import List
from packages.clips.curation.pipeline import CurationPipeline
from packages.clips.curation.models import CuratedClip, ViralityScore
from packages.clips.curation.agents.finder import FinderAgent

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
@patch('packages.clips.curation.agents.finder.get_llm')
@patch('packages.clips.curation.agents.critic.get_llm')
@patch('packages.clips.curation.agents.ranker.get_llm')
def pipeline(mock_ranker, mock_critic, mock_finder):
    # Instantiate without external API calls by mocking them later
    mock_finder.return_value = MagicMock()
    mock_critic.return_value = MagicMock()
    mock_ranker.return_value = MagicMock()
    return CurationPipeline(temperature=0.0)

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

def test_deduplicate_clips(pipeline):
    """Ensure clips with overlapping timestamps accurately deduplicate, keeping the highest score."""
    from packages.clips.curation.models import FinderCandidate
    clip1 = FinderCandidate(
        start_time=10.0, end_time=40.0, title="A", summary="A", reasoning="A"
    )
    clip2 = FinderCandidate(
        start_time=15.0, end_time=45.0, title="B", summary="B", reasoning="B"
    )

    # test via finder directly
    unique = pipeline.finder._deduplicate_candidates([clip1, clip2], overlap_threshold=0.5)
    
    assert len(unique) == 1
    # Should keep clip1 because its duration is 30. clip2 is 30. 
    # Deduplicate_candidates keeps the longer one. If equal, keeps the first one it found.
    assert unique[0].title == "A"

def test_clip_duration_validation(pipeline):
    """Verify that too short/long clips are properly flagged for manual review or invalidated."""
    clip = CuratedClip(start_time=10, end_time=50, title="Test", summary="Test") # 40s
    assert pipeline._validate_clip_duration(clip, min_duration=30, max_duration=60) == 'valid'
    
    clip.start_time = 10; clip.end_time = 25 # 15s
    assert pipeline._validate_clip_duration(clip, min_duration=30, max_duration=60) == 'invalid'
    
    clip.virality_score = ViralityScore(hook_strength=10, storytelling=10, quotability=10, controversy=10, optimal_duration=10, energy_level=10) # Total > 50
    assert pipeline._validate_clip_duration(clip, min_duration=30, max_duration=60) == 'pending'
    
    clip.start_time = 10; clip.end_time = 80 # 70s
    assert pipeline._validate_clip_duration(clip, min_duration=30, max_duration=60) == 'pending'
    
    clip.start_time = 10; clip.end_time = 200 # 190s
    assert pipeline._validate_clip_duration(clip, min_duration=30, max_duration=60) == 'invalid'

@patch('packages.clips.curation.agents.finder.FinderAgent.find_candidates')
@patch('packages.clips.curation.agents.critic.CriticAgent.evaluate_candidates')
@patch('packages.clips.curation.agents.ranker.RankerAgent.rank_clips')
@patch('packages.clips.curation.agents.ranker.RankerAgent.generate_captions')
def test_full_curation_pipeline_mocked(mock_generate_captions, mock_rank_clips, mock_evaluate, mock_find, pipeline, sample_transcript):
    from packages.clips.curation.models import FinderCandidate, CriticClip, CuratedClip, ViralityScore
    
    mock_find.return_value = [FinderCandidate(start_time=10.0, end_time=40.0, title="T", summary="S", reasoning="R")]
    mock_evaluate.return_value = [CriticClip(start_time=10.0, end_time=40.0, title="T", summary="S", reasoning="R", approved=True)]
    mock_rank_clips.return_value = [
        CuratedClip(
            start_time=10.0, end_time=40.0, title="College Dropout to AI Builder", summary="S", 
            virality_score=ViralityScore(storytelling=10)
        )
    ]
    
    def cap_mock(clips, *args, **kwargs):
        clips[0].social_caption = "You won't believe this story! 🤯"
        clips[0].caption_hashtags = ["#AI"]
        return clips
    mock_generate_captions.side_effect = cap_mock

    results = pipeline.curate(
        transcript=sample_transcript,
        top_n=1,
        min_duration=30,
        max_duration=60,
        episode_number=1,
        guest_name="Mock Guest"
    )

    assert len(results) == 1
    clip = results[0]
    
    assert clip.title == "College Dropout to AI Builder"
    assert clip.pending_review is False
    assert clip.virality_score.storytelling == 10
    
    assert clip.social_caption == "You won't believe this story! 🤯"
    assert "#AI" in clip.caption_hashtags
