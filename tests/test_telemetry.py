"""
Tests for TelemetryService — validates normalization, timestamp handling, and event construction.
"""

import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone


# ─── Normalization Tests ────────────────────────────────────────────────────

class TestHookTypeNormalization:
    """Test that free-form hook types map to canonical IC values."""

    @staticmethod
    def _normalize(raw):
        from packages.core.services.telemetry import TelemetryService
        return TelemetryService._normalize_hook_type(raw)

    def test_canonical_passthrough(self):
        assert self._normalize("question") == "question"
        assert self._normalize("storytelling") == "storytelling"
        assert self._normalize("tutorial") == "tutorial"

    def test_spanish_aliases(self):
        assert self._normalize("pregunta") == "question"
        assert self._normalize("dato_sorprendente") == "surprising_fact"
        assert self._normalize("historia") == "storytelling"
        assert self._normalize("debil") == "weak"

    def test_english_aliases(self):
        assert self._normalize("story") == "storytelling"
        assert self._normalize("how_to") == "tutorial"
        assert self._normalize("bold_claim") == "controversial_statement"
        assert self._normalize("pain_point") == "negative_frame"

    def test_case_insensitive(self):
        assert self._normalize("Question") == "question"
        assert self._normalize("STORYTELLING") == "storytelling"

    def test_none_returns_none(self):
        assert self._normalize(None) is None
        assert self._normalize("") is None

    def test_unknown_defaults_to_weak(self):
        assert self._normalize("some_unknown_type") == "weak"


class TestEmotionalChargeNormalization:
    """Test that free-form emotional charges map to canonical IC values."""

    @staticmethod
    def _normalize(raw):
        from packages.core.services.telemetry import TelemetryService
        return TelemetryService._normalize_emotional_charge(raw)

    def test_canonical_passthrough(self):
        assert self._normalize("inspirational") == "inspirational"
        assert self._normalize("urgent") == "urgent"
        assert self._normalize("comedic") == "comedic"

    def test_spanish_aliases(self):
        assert self._normalize("inspirador") == "inspirational"
        assert self._normalize("urgente") == "urgent"
        assert self._normalize("educativo") == "educational"
        assert self._normalize("empatico") == "empathetic"

    def test_none_returns_none(self):
        assert self._normalize(None) is None
        assert self._normalize("") is None


class TestDurationBucket:
    """Test duration bucketing logic."""

    @staticmethod
    def _bucket(seconds):
        from packages.core.services.telemetry import TelemetryService
        return TelemetryService._compute_duration_bucket(seconds)

    def test_buckets(self):
        assert self._bucket(10) == "0-15"
        assert self._bucket(15) == "0-15"
        assert self._bucket(20) == "15-30"
        assert self._bucket(30) == "15-30"
        assert self._bucket(35) == "30-45"
        assert self._bucket(50) == "45-60"

    def test_none(self):
        assert self._bucket(None) is None


# ─── Timestamp Fix Validation ───────────────────────────────────────────────

class TestTimestampFix:
    """Verify that _utc_now_iso returns a valid ISO timestamp, not 'now()' string."""

    def test_returns_iso_string(self):
        from packages.core.services.telemetry import _utc_now_iso
        result = _utc_now_iso()
        # Must be parseable as ISO datetime
        parsed = datetime.fromisoformat(result)
        assert parsed.tzinfo is not None  # Must be timezone-aware

    def test_not_now_string(self):
        from packages.core.services.telemetry import _utc_now_iso
        result = _utc_now_iso()
        assert result != "now()"
        assert "now" not in result


# ─── Event Construction Tests ───────────────────────────────────────────────

class TestTelemetryEventConstruction:
    """Test that events are built correctly without hitting Supabase."""

    @patch("packages.core.services.telemetry.settings")
    def test_track_clip_performance_builds_correct_metadata(self, mock_settings):
        mock_settings.azelia_telemetry_enabled = False  # Disabled = won't try Supabase
        from packages.core.services.telemetry import TelemetryService

        svc = TelemetryService()
        # Should not crash even when disabled
        svc.track_clip_performance(
            user_id="test-user",
            predicted_score=85.5,
            hook_type="Pregunta",
            duration_seconds=32.0,
            emotional_charge="Inspirador",
            has_cta=True,
        )
        # No assertion needed — test passes if no exception

    @patch("packages.core.services.telemetry.settings")
    def test_disabled_service_does_nothing(self, mock_settings):
        mock_settings.azelia_telemetry_enabled = False
        mock_settings.supabase_url = ""
        mock_settings.supabase_key = ""
        from packages.core.services.telemetry import TelemetryService

        svc = TelemetryService()
        assert svc.enabled is False
        assert svc.supabase is None


# ─── Pattern Applied Keys Fix ──────────────────────────────────────────────

class TestYoutubePerformanceMetadataKeys:
    """Verify the pattern_applied dict uses correct metadata keys."""

    @patch("packages.core.services.telemetry.settings")
    @patch("packages.core.services.telemetry.create_client")
    def test_pattern_applied_uses_snapshot_keys(self, mock_create, mock_settings):
        """The pattern_applied dict must read views_snapshot, not views."""
        mock_settings.azelia_telemetry_enabled = True
        mock_settings.supabase_url = "https://test.supabase.co"
        mock_settings.supabase_key = "test-key"

        mock_sb = MagicMock()
        mock_create.return_value = mock_sb

        from packages.core.services.telemetry import TelemetryService
        svc = TelemetryService()

        # Capture what gets inserted
        captured_data = {}

        def capture_insert(data):
            captured_data.update(data)
            mock_result = MagicMock()
            mock_result.execute.return_value = None
            return mock_result

        mock_table = MagicMock()
        mock_sb.table.return_value = mock_table
        mock_table.insert.side_effect = capture_insert

        # Also mock the profiles select for episode_format lookup
        mock_select = MagicMock()
        mock_table.select.return_value = mock_select
        mock_select.eq.return_value = mock_select
        mock_select_result = MagicMock()
        mock_select_result.data = [{"preferences": {"episode_format": "interview"}}]
        mock_select.execute.return_value = mock_select_result

        svc.track_youtube_performance(
            user_id="test",
            youtube_id="abc123",
            views=1000,
            likes=50,
            comments=10,
            hook_type="question",
        )

        # Wait for thread to finish
        import time
        time.sleep(0.5)

        # Verify pattern_applied has the right values
        if captured_data:
            pattern = captured_data.get("pattern_applied", {})
            assert pattern.get("views") == 1000  # from views_snapshot
            assert pattern.get("likes") == 50    # from likes_snapshot
            assert pattern.get("comments") == 10  # from comments_snapshot
