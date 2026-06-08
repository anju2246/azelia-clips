"""
Tests for brief builder (T1 - Domain models + brief builder + persistence).
All tests are expected to FAIL until implementation is complete.
"""
import pytest
import json
from pathlib import Path
from packages.clips.curation.brief_models import BriefCandidate, ChatMessage, BriefSession
from packages.clips.curation.brief_builder import build_session, save_session, load_session


# ==========================================
# Domain Model Tests
# ==========================================

def test_brief_candidate_model_creates_with_required_fields():
    """Verify BriefCandidate can be instantiated with all required fields."""
    candidate = BriefCandidate(
        id=1,
        start_time=120.0,
        end_time=168.0,
        title="Test Title",
        summary="Test Summary",
        reasoning="Test Reasoning",
        score=85.0,
        critic_approved=True,
        above_threshold=True,
        selected=True,
        origin="curation"
    )
    assert candidate.id == 1
    assert candidate.start_time == 120.0
    assert candidate.origin == "curation"
    assert candidate.critic_approved is True


def test_chat_message_model_with_optional_change_summary():
    """Verify ChatMessage can be created with and without change_summary."""
    msg1 = ChatMessage(role="user", content="Show me the clips")
    assert msg1.role == "user"
    assert msg1.content == "Show me the clips"
    assert msg1.change_summary is None

    msg2 = ChatMessage(
        role="assistant",
        content="Here are the clips",
        change_summary="Added clip #3"
    )
    assert msg2.change_summary == "Added clip #3"


def test_brief_session_to_dict_roundtrip():
    """Verify BriefSession.to_dict() and from_dict() preserve all fields."""
    candidate = BriefCandidate(
        id=1,
        start_time=120.0,
        end_time=168.0,
        title="Test",
        summary="Summary",
        reasoning="Reasoning",
        score=85.0,
        critic_approved=True,
        above_threshold=True,
        selected=True,
        origin="curation"
    )
    message = ChatMessage(role="user", content="Hello")

    session = BriefSession(
        job_id="job_123",
        episode_id="EP001",
        status="open",
        candidates=[candidate],
        messages=[message],
        created_at="2026-06-08T10:00:00",
        updated_at="2026-06-08T10:00:00"
    )

    session_dict = session.to_dict()
    restored_session = BriefSession.from_dict(session_dict)

    assert restored_session.job_id == session.job_id
    assert restored_session.episode_id == session.episode_id
    assert restored_session.status == session.status
    assert len(restored_session.candidates) == 1
    assert restored_session.candidates[0].id == 1
    assert restored_session.candidates[0].title == "Test"
    assert len(restored_session.messages) == 1
    assert restored_session.messages[0].role == "user"


def test_brief_session_status_values():
    """Verify status can be 'open', 'approved', or 'cancelled'."""
    for status in ["open", "approved", "cancelled"]:
        session = BriefSession(
            job_id="job_123",
            episode_id="EP001",
            status=status,
            candidates=[],
            messages=[],
            created_at="2026-06-08T10:00:00",
            updated_at="2026-06-08T10:00:00"
        )
        assert session.status == status


# ==========================================
# Brief Builder Tests
# ==========================================

@pytest.fixture
def fixtures_dir():
    """Return path to test fixtures directory."""
    return Path(__file__).parent / "fixtures" / "brief"


@pytest.fixture
def sample_job_dir(tmp_path, fixtures_dir):
    """Create a sample job directory with curation artifacts."""
    job_dir = tmp_path / "job_123"
    job_dir.mkdir()

    # Copy fixture files
    curation_src = fixtures_dir / "curation.json"
    critic_src = fixtures_dir / "critic_decisions.json"

    with open(curation_src) as f:
        curation_data = f.read()
    with open(critic_src) as f:
        critic_data = f.read()

    (job_dir / "curation.json").write_text(curation_data)
    (job_dir / "critic_decisions.json").write_text(critic_data)

    return job_dir


def test_build_session_merges_approved_and_rejected(sample_job_dir):
    """
    build_session loads curation.json (approved) and critic_decisions.json (rejected),
    merges them with correct critic_approved flags.
    """
    session = build_session(sample_job_dir, "EP001", min_score=70)

    # Fixture has 3 approved clips from curation.json + 2 rejected from critic_decisions.json
    assert len(session.candidates) == 5, "Should have 5 total candidates (3 approved + 2 rejected)"

    # Count critic_approved flags
    approved_count = sum(1 for c in session.candidates if c.critic_approved)
    rejected_count = sum(1 for c in session.candidates if not c.critic_approved)

    assert approved_count == 3, "Should have 3 critic-approved candidates from curation.json"
    assert rejected_count == 2, "Should have 2 critic-rejected candidates from critic_decisions.json"

    # Verify rejected clips have origin="rescued"
    rejected_candidates = [c for c in session.candidates if not c.critic_approved]
    for candidate in rejected_candidates:
        assert candidate.origin == "rescued", "Rejected clips should have origin='rescued'"
        assert candidate.selected is False, "Rejected clips should not be selected initially"


def test_candidate_ids_are_stable_1based_sorted_by_score(sample_job_dir):
    """
    Candidate IDs are 1-based, sequential, and ordered by score descending.
    """
    session = build_session(sample_job_dir, "EP001", min_score=70)

    # Check IDs are 1-based and sequential
    ids = [c.id for c in session.candidates]
    assert ids == list(range(1, len(session.candidates) + 1)), "IDs should be 1-based sequential"

    # Check sorted by score descending
    scores = [c.score for c in session.candidates]
    assert scores == sorted(scores, reverse=True), "Candidates should be sorted by score descending"


def test_above_threshold_flag(sample_job_dir):
    """
    Candidate with total >= min_score gets above_threshold=True and selected=True.
    Candidate with total < min_score gets both False.
    """
    session = build_session(sample_job_dir, "EP001", min_score=70)

    # Fixture clip 1: total = 85 (above)
    # Fixture clip 2: total = 55 (below)
    # Fixture clip 3: total = 70 (exactly at threshold)
    # Rejected clips: score ≈ 0 (below)

    for candidate in session.candidates:
        if candidate.score >= 70:
            assert candidate.above_threshold is True, f"Candidate with score {candidate.score} should be above_threshold"
            # Only critic-approved candidates above threshold should be selected
            if candidate.critic_approved:
                assert candidate.selected is True, f"Approved candidate with score {candidate.score} should be selected"
        else:
            assert candidate.above_threshold is False, f"Candidate with score {candidate.score} should not be above_threshold"
            assert candidate.selected is False, f"Candidate with score {candidate.score} should not be selected"


def test_virality_score_total_computed_correctly(sample_job_dir):
    """
    Verify virality score totals are computed from the 10 dimensions.
    Fixture clip 1: all dimensions sum to 85
    Fixture clip 2: all dimensions sum to 55
    Fixture clip 3: all dimensions are 7, sum to 70
    """
    session = build_session(sample_job_dir, "EP001", min_score=70)

    # Find the candidates by their titles (from fixtures)
    candidates_by_title = {c.title: c for c in session.candidates}

    clip1 = candidates_by_title.get("Why AI Will Replace Most Jobs")
    assert clip1 is not None, "Should find clip 1"
    assert clip1.score == 85, "Clip 1 should have score 85 (9+8+9+8+9+8+8+9+9+8)"

    clip2 = candidates_by_title.get("My Biggest Failure")
    assert clip2 is not None, "Should find clip 2"
    assert clip2.score == 55, "Clip 2 should have score 55 (5+6+6+4+6+5+7+5+6+5)"

    clip3 = candidates_by_title.get("The Secret to Success")
    assert clip3 is not None, "Should find clip 3"
    assert clip3.score == 70, "Clip 3 should have score 70 (all 7s * 10 dimensions)"


def test_session_roundtrip_persistence(sample_job_dir):
    """
    save_session then load_session returns an equal session.
    """
    # Build initial session
    session = build_session(sample_job_dir, "EP001", min_score=70)

    # Add a message
    session.messages.append(ChatMessage(
        role="user",
        content="Show me the top clips",
        change_summary=None
    ))

    # Save
    save_session(sample_job_dir, session)

    # Verify file exists
    session_file = sample_job_dir / "brief_session.json"
    assert session_file.exists(), "brief_session.json should be created"

    # Load
    loaded_session = load_session(sample_job_dir)

    assert loaded_session is not None, "Should load session successfully"
    assert loaded_session.job_id == session.job_id
    assert loaded_session.episode_id == session.episode_id
    assert loaded_session.status == session.status
    assert len(loaded_session.candidates) == len(session.candidates)
    assert len(loaded_session.messages) == 1
    assert loaded_session.messages[0].content == "Show me the top clips"

    # Verify candidate details
    for i, (original, loaded) in enumerate(zip(session.candidates, loaded_session.candidates)):
        assert loaded.id == original.id, f"Candidate {i} id mismatch"
        assert loaded.title == original.title, f"Candidate {i} title mismatch"
        assert loaded.score == original.score, f"Candidate {i} score mismatch"
        assert loaded.critic_approved == original.critic_approved, f"Candidate {i} critic_approved mismatch"
        assert loaded.above_threshold == original.above_threshold, f"Candidate {i} above_threshold mismatch"
        assert loaded.selected == original.selected, f"Candidate {i} selected mismatch"
        assert loaded.origin == original.origin, f"Candidate {i} origin mismatch"


def test_build_session_no_critic_decisions_file(tmp_path, fixtures_dir):
    """
    When critic_decisions.json doesn't exist, build_session still works
    and returns only curation candidates (no crash).
    """
    job_dir = tmp_path / "job_no_critic"
    job_dir.mkdir()

    # Copy only curation.json (no critic_decisions.json)
    curation_src = fixtures_dir / "curation.json"
    with open(curation_src) as f:
        curation_data = f.read()
    (job_dir / "curation.json").write_text(curation_data)

    # Should not crash
    session = build_session(job_dir, "EP001", min_score=70)

    # Should have only the 3 curation candidates
    assert len(session.candidates) == 3, "Should have only 3 candidates from curation.json"

    # All should be critic_approved (from curation)
    for candidate in session.candidates:
        assert candidate.critic_approved is True, "All candidates from curation.json should be critic_approved"


def test_load_session_returns_none_when_file_missing(tmp_path):
    """
    load_session returns None when brief_session.json doesn't exist.
    """
    job_dir = tmp_path / "empty_job"
    job_dir.mkdir()

    session = load_session(job_dir)
    assert session is None, "Should return None when session file doesn't exist"
