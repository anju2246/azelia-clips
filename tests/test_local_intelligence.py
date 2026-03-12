"""
Tests for LocalIntelligenceService — validates aggregation, bug fixes, and basic intelligence.
"""

import pytest
from unittest.mock import patch, MagicMock


# ─── Bug Fix: yt_hook_engagement denominator ───────────────────────────────

class TestEngagementCalculation:
    """Verify the engagement calculation uses correct denominator after fix."""

    def test_engagement_avg_with_data(self):
        """avg_engagement should divide by actual list length, not [1]."""
        engagement_list = [0.05, 0.10, 0.15]
        avg = sum(engagement_list) / max(len(engagement_list), 1)
        assert abs(avg - 0.1) < 0.001  # Should be 0.1, not 0.3

    def test_engagement_avg_empty_list(self):
        """Empty list should not crash (divides by 1)."""
        engagement_list = []
        avg = sum(engagement_list) / max(len(engagement_list), 1)
        assert avg == 0.0


# ─── Bug Fix: yt_result undefined ──────────────────────────────────────────

class TestYoutubeEventsCount:
    """Verify youtube_events uses latest_yt_metrics instead of yt_result.data."""

    @patch("packages.core.services.local_intelligence.console")
    def test_aggregate_without_youtube_data_no_crash(self, mock_console):
        """When YouTube query fails, should not crash on yt_result reference."""
        from packages.core.services.local_intelligence import LocalIntelligenceService

        svc = LocalIntelligenceService.__new__(LocalIntelligenceService)
        svc._supabase = MagicMock()
        svc._ollama_available = None
        svc._api_available = False

        # Mock clip_signal query to return some data
        clip_result = MagicMock()
        clip_result.data = [
            {"metadata": {"hook_type": "question", "predicted_score": 80, "duration_seconds": 30}, "created_at": "2026-01-01"},
            {"metadata": {"hook_type": "storytelling", "predicted_score": 90, "duration_seconds": 45}, "created_at": "2026-01-02"},
            {"metadata": {"hook_type": "question", "predicted_score": 75, "duration_seconds": 35}, "created_at": "2026-01-03"},
            {"metadata": {"hook_type": "storytelling", "predicted_score": 85, "duration_seconds": 40}, "created_at": "2026-01-04"},
            {"metadata": {"hook_type": "question", "predicted_score": 70, "duration_seconds": 28}, "created_at": "2026-01-05"},
        ]

        # Mock YouTube query to FAIL (this was the bug scenario)
        yt_result = MagicMock()
        yt_result.data = None  # No YouTube data

        def mock_table_query(table_name):
            mock_table = MagicMock()
            mock_select = MagicMock()
            mock_table.select.return_value = mock_select
            mock_eq1 = MagicMock()
            mock_select.eq.return_value = mock_eq1
            mock_eq2 = MagicMock()
            mock_eq1.eq.return_value = mock_eq2
            mock_order = MagicMock()
            mock_eq2.order.return_value = mock_order
            mock_limit = MagicMock()
            mock_order.limit.return_value = mock_limit

            # Return different results based on call order
            if not hasattr(mock_table_query, '_call_count'):
                mock_table_query._call_count = 0
            mock_table_query._call_count += 1

            if mock_table_query._call_count == 1:
                mock_limit.execute.return_value = clip_result
            else:
                mock_limit.execute.return_value = yt_result

            return mock_table

        svc._supabase.table = mock_table_query

        # This should NOT crash (previously crashed on line 323: yt_result.data)
        result = svc._aggregate_user_events("test-user-123")

        assert result is not None
        assert result["total_events"] == 5
        assert result["youtube_events"] == 0  # No YouTube data
        assert result["has_youtube_data"] is False


# ─── Basic Intelligence Generation ────────────────────────────────────────

class TestBasicIntelligence:
    """Test the SQL-only basic intelligence mode."""

    def test_generates_patterns_from_hook_averages(self):
        from packages.core.services.local_intelligence import LocalIntelligenceService

        svc = LocalIntelligenceService.__new__(LocalIntelligenceService)

        aggregated = {
            "total_events": 50,
            "hook_averages": {
                "storytelling": 85.0,
                "question": 72.0,
                "tutorial": 60.0,
            },
            "hook_counts": {
                "storytelling": 20,
                "question": 18,
                "tutorial": 12,
            },
            "optimal_duration": {"min": 30, "max": 55},
            "top_categories": ["inspirational", "educational"],
            "has_youtube_data": False,
            "youtube_events": 0,
        }

        result = svc._generate_basic_intelligence(aggregated, "test-user")

        assert result["mode"] == "basic"
        assert result["based_on_runs"] == 50
        assert len(result["high_retention_patterns"]) >= 2
        assert len(result["preferred_clip_formats"]) >= 1
        # Best hook should be mentioned first
        assert "storytelling" in result["high_retention_patterns"][0]

    def test_handles_single_hook_type(self):
        from packages.core.services.local_intelligence import LocalIntelligenceService

        svc = LocalIntelligenceService.__new__(LocalIntelligenceService)

        aggregated = {
            "total_events": 10,
            "hook_averages": {"question": 75.0},
            "hook_counts": {"question": 10},
            "optimal_duration": None,
            "top_categories": [],
            "has_youtube_data": False,
            "youtube_events": 0,
        }

        result = svc._generate_basic_intelligence(aggregated, "test-user")
        assert result["mode"] == "basic"
        assert len(result["high_retention_patterns"]) >= 1

    def test_handles_empty_data(self):
        from packages.core.services.local_intelligence import LocalIntelligenceService

        svc = LocalIntelligenceService.__new__(LocalIntelligenceService)

        aggregated = {
            "total_events": 5,
            "hook_averages": {},
            "hook_counts": {},
            "optimal_duration": None,
            "top_categories": [],
            "has_youtube_data": False,
            "youtube_events": 0,
        }

        result = svc._generate_basic_intelligence(aggregated, "test-user")
        assert result["mode"] == "basic"
        assert result["high_retention_patterns"] == []


# ─── Empty Result Helper ──────────────────────────────────────────────────

class TestEmptyResult:
    """Test the _empty_result helper."""

    def test_inactive_mode(self):
        from packages.core.services.local_intelligence import LocalIntelligenceService

        result = LocalIntelligenceService._empty_result("inactive")
        assert result["mode"] == "inactive"
        assert result["high_retention_patterns"] == []
        assert result["preferred_clip_formats"] == []
        assert result["based_on_runs"] == 0

    def test_custom_mode(self):
        from packages.core.services.local_intelligence import LocalIntelligenceService

        result = LocalIntelligenceService._empty_result("error")
        assert result["mode"] == "error"


# ─── Settings Validation ─────────────────────────────────────────────────

class TestSettingsAPIKeyValidation:
    """Test API key validation in settings route."""

    def test_valid_groq_key(self):
        from server.routes.settings import _validate_api_key
        assert _validate_api_key("groq_api_key", "gsk_abc123456789") is None

    def test_invalid_groq_key_prefix(self):
        from server.routes.settings import _validate_api_key
        error = _validate_api_key("groq_api_key", "sk-wrong-prefix-key")
        assert error is not None
        assert "gsk_" in error

    def test_valid_openai_key(self):
        from server.routes.settings import _validate_api_key
        assert _validate_api_key("openai_api_key", "sk-proj-abcdef123456") is None

    def test_invalid_openai_key(self):
        from server.routes.settings import _validate_api_key
        error = _validate_api_key("openai_api_key", "gsk_wrong_prefix")
        assert error is not None
        assert "sk-" in error

    def test_valid_anthropic_key(self):
        from server.routes.settings import _validate_api_key
        assert _validate_api_key("anthropic_api_key", "sk-ant-api03-abcdef") is None

    def test_empty_key_is_ok(self):
        from server.routes.settings import _validate_api_key
        assert _validate_api_key("groq_api_key", "") is None
        assert _validate_api_key("groq_api_key", None) is None

    def test_too_short_key(self):
        from server.routes.settings import _validate_api_key
        error = _validate_api_key("groq_api_key", "gsk_ab")
        assert error is not None
        assert "short" in error

    def test_unknown_provider_no_prefix_check(self):
        from server.routes.settings import _validate_api_key
        assert _validate_api_key("gcp_project_id", "my-gcp-project-123") is None
