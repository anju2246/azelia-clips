"""
Tests for IC Cascade — market intelligence blending with local patterns.
"""

import pytest
from unittest.mock import patch, MagicMock


# ─── Signal to Hint Transformation ─────────────────────────────────────────

class TestSignalsToHints:
    """Test that raw IC signals transform to user-facing hint strings."""

    @staticmethod
    def _to_hints(signals):
        from packages.core.services.local_intelligence import LocalIntelligenceService
        return LocalIntelligenceService._signals_to_hints(signals)

    def test_clip_hook_signal(self):
        signals = [{
            "signal_type": "clip_hook",
            "pattern": {"hook_type": "storytelling"},
            "confidence": 0.8,
        }]
        hints = self._to_hints(signals)
        assert len(hints) == 1
        assert "storytelling" in hints[0]
        assert "hook" in hints[0].lower() or "Prioriza" in hints[0]

    def test_emotion_pattern_signal(self):
        signals = [{
            "signal_type": "emotion_pattern",
            "pattern": {"emotional_charge": "inspirational"},
            "confidence": 0.6,
        }]
        hints = self._to_hints(signals)
        assert len(hints) == 1
        assert "inspirational" in hints[0]

    def test_duration_pattern_signal(self):
        signals = [{
            "signal_type": "duration_pattern",
            "pattern": {"duration_bucket": "30-45s"},
            "confidence": 0.6,
        }]
        hints = self._to_hints(signals)
        assert len(hints) == 1
        assert "30-45s" in hints[0]

    def test_topic_trend_signal(self):
        signals = [{
            "signal_type": "topic_trend",
            "pattern": {"topic": "inteligencia_artificial", "topic_display": "Inteligencia Artificial"},
            "confidence": 0.6,
        }]
        hints = self._to_hints(signals)
        assert len(hints) == 1
        assert "Inteligencia Artificial" in hints[0]

    def test_trend_direction_prefix(self):
        signals = [{
            "signal_type": "clip_hook",
            "pattern": {"hook_type": "question"},
            "trend_direction": "rising",
            "confidence": 0.8,
        }]
        hints = self._to_hints(signals)
        assert "TENDENCIA AL ALZA" in hints[0]

    def test_falling_trend_prefix(self):
        signals = [{
            "signal_type": "emotion_pattern",
            "pattern": {"emotional_charge": "outrage"},
            "trend_direction": "falling",
            "confidence": 0.6,
        }]
        hints = self._to_hints(signals)
        assert "TENDENCIA A LA BAJA" in hints[0]

    def test_stable_no_prefix(self):
        signals = [{
            "signal_type": "clip_hook",
            "pattern": {"hook_type": "tutorial"},
            "trend_direction": "stable",
            "confidence": 0.6,
        }]
        hints = self._to_hints(signals)
        assert "TENDENCIA" not in hints[0]

    def test_empty_signals(self):
        assert self._to_hints([]) == []

    def test_unknown_signal_type_skipped(self):
        signals = [{"signal_type": "unknown_type", "pattern": {}}]
        assert self._to_hints(signals) == []

    def test_multiple_signals(self):
        signals = [
            {"signal_type": "clip_hook", "pattern": {"hook_type": "storytelling"}, "confidence": 0.8},
            {"signal_type": "emotion_pattern", "pattern": {"emotional_charge": "comedic"}, "confidence": 0.6},
            {"signal_type": "duration_pattern", "pattern": {"duration_bucket": "15-30s"}, "confidence": 0.4},
        ]
        hints = self._to_hints(signals)
        assert len(hints) == 3

    def test_cta_effect_signal(self):
        signals = [{
            "signal_type": "cta_effect",
            "pattern": {"cta_lift": 0.023},
            "confidence": 0.6,
        }]
        hints = self._to_hints(signals)
        assert len(hints) == 1
        assert "CTA" in hints[0]

    def test_temporal_pattern_signal(self):
        signals = [{
            "signal_type": "temporal_pattern",
            "pattern": {"publish_day": "Monday", "publish_hour": 14},
            "confidence": 0.6,
        }]
        hints = self._to_hints(signals)
        assert len(hints) == 1
        assert "Monday" in hints[0]
        assert "14" in hints[0]


# ─── Bayesian Blending ─────────────────────────────────────────────────────

class TestBayesianBlending:
    """Test the bayesian weight computation from ic_contract."""

    def test_new_user_favors_market(self):
        from packages.core.ic_contract import compute_bayesian_weight
        w_user, w_market = compute_bayesian_weight(5)
        assert w_user == 0.05
        assert w_market == 0.95

    def test_moderate_user_balanced(self):
        from packages.core.ic_contract import compute_bayesian_weight
        w_user, w_market = compute_bayesian_weight(50)
        assert w_user == 0.5
        assert w_market == 0.5

    def test_experienced_user_favors_local(self):
        from packages.core.ic_contract import compute_bayesian_weight
        w_user, w_market = compute_bayesian_weight(100)
        assert w_user == 1.0
        assert w_market == 0.0

    def test_very_experienced_user_caps_at_1(self):
        from packages.core.ic_contract import compute_bayesian_weight
        w_user, w_market = compute_bayesian_weight(500)
        assert w_user == 1.0
        assert w_market == 0.0


# ─── Tier Gating ───────────────────────────────────────────────────────────

class TestTierGating:
    """Test that IC cascade only activates for Pro+ users."""

    @patch("packages.core.services.local_intelligence.console")
    def test_community_user_gets_no_ic_blend(self, mock_console):
        """Community user should not get IC signals blended in."""
        from packages.core.services.local_intelligence import LocalIntelligenceService

        svc = LocalIntelligenceService.__new__(LocalIntelligenceService)
        svc._supabase = MagicMock()
        svc._ollama_available = False
        svc._api_available = False

        # Mock tier lookup to return 'community'
        mock_result = MagicMock()
        mock_result.data = {"tier": "community"}

        mock_table = MagicMock()
        svc._supabase.table.return_value = mock_table
        mock_select = MagicMock()
        mock_table.select.return_value = mock_select
        mock_eq = MagicMock()
        mock_select.eq.return_value = mock_eq
        mock_single = MagicMock()
        mock_eq.single.return_value = mock_single
        mock_single.execute.return_value = mock_result

        tier = svc._get_user_tier("community-user-123")
        assert tier == "community"

    @patch("packages.core.services.local_intelligence.console")
    def test_pro_user_gets_tier(self, mock_console):
        """Pro user tier should be detected."""
        from packages.core.services.local_intelligence import LocalIntelligenceService

        svc = LocalIntelligenceService.__new__(LocalIntelligenceService)
        svc._supabase = MagicMock()

        mock_result = MagicMock()
        mock_result.data = {"tier": "pro"}

        mock_table = MagicMock()
        svc._supabase.table.return_value = mock_table
        mock_select = MagicMock()
        mock_table.select.return_value = mock_select
        mock_eq = MagicMock()
        mock_select.eq.return_value = mock_eq
        mock_single = MagicMock()
        mock_eq.single.return_value = mock_single
        mock_single.execute.return_value = mock_result

        tier = svc._get_user_tier("pro-user-123")
        assert tier == "pro"

    @patch("packages.core.services.local_intelligence.console")
    def test_missing_tier_defaults_to_community(self, mock_console):
        """If tier is missing or None, default to community."""
        from packages.core.services.local_intelligence import LocalIntelligenceService

        svc = LocalIntelligenceService.__new__(LocalIntelligenceService)
        svc._supabase = MagicMock()

        mock_result = MagicMock()
        mock_result.data = {"tier": None}

        mock_table = MagicMock()
        svc._supabase.table.return_value = mock_table
        mock_select = MagicMock()
        mock_table.select.return_value = mock_select
        mock_eq = MagicMock()
        mock_select.eq.return_value = mock_eq
        mock_single = MagicMock()
        mock_eq.single.return_value = mock_single
        mock_single.execute.return_value = mock_result

        tier = svc._get_user_tier("unknown-user")
        assert tier == "community"


# ─── Blend Integration ─────────────────────────────────────────────────────

class TestBlendWithIC:
    """Test the full blending flow."""

    @patch("packages.core.services.local_intelligence.console")
    def test_blend_adds_ic_hints_to_patterns(self, mock_console):
        """IC hints should be appended to local patterns."""
        from packages.core.services.local_intelligence import LocalIntelligenceService

        svc = LocalIntelligenceService.__new__(LocalIntelligenceService)
        svc._supabase = MagicMock()

        # Mock _get_user_context
        ctx_result = MagicMock()
        ctx_result.data = {
            "preferences": {"region": "Mexico", "episode_format": "interview"},
            "content_niche": "business",
        }

        # Mock _fetch_ic_signals — return fake signals
        ic_result = MagicMock()
        ic_result.data = [
            {
                "signal_type": "clip_hook",
                "pattern": {"hook_type": "storytelling"},
                "performance_premium": 6.5,
                "confidence": 0.8,
                "trend_direction": "rising",
                "trend_velocity": 0.15,
                "saturation": "emerging",
                "source_type": "podintel_public",
                "is_active": True,
            },
            {
                "signal_type": "emotion_pattern",
                "pattern": {"emotional_charge": "inspirational"},
                "performance_premium": 3.2,
                "confidence": 0.6,
                "trend_direction": "stable",
                "trend_velocity": 0.02,
                "saturation": "differentiating",
                "source_type": "podintel_public",
                "is_active": True,
            },
        ]

        call_count = {"n": 0}

        def mock_table(name):
            mock_t = MagicMock()
            mock_s = MagicMock()
            mock_t.select.return_value = mock_s
            mock_eq1 = MagicMock()
            mock_s.eq.return_value = mock_eq1

            if name == "profiles":
                mock_single = MagicMock()
                mock_eq1.single.return_value = mock_single
                mock_single.execute.return_value = ctx_result
            elif name == "ic_signals":
                # Chain the query builder
                mock_eq1.eq.return_value = mock_eq1
                mock_eq1.gte.return_value = mock_eq1
                mock_eq1.order.return_value = mock_eq1
                mock_eq1.limit.return_value = mock_eq1
                mock_eq1.execute.return_value = ic_result

            return mock_t

        svc._supabase.table = mock_table

        local_result = {
            "high_retention_patterns": ["Local pattern 1", "Local pattern 2"],
            "preferred_clip_formats": ["Format 1"],
            "based_on_runs": 10,  # Low = IC should get high weight
            "mode": "basic",
        }

        blended = svc._blend_with_ic(local_result, "pro-user-123")

        # Should have both local and IC patterns (at least 1 of each)
        assert len(blended["high_retention_patterns"]) >= 2
        assert blended["ic_signals_count"] == 2
        assert blended["blend_weights"]["podintel"] > 0.5  # 10 runs → market dominates
        # Should contain at least one local and one IC hint
        all_text = " ".join(blended["high_retention_patterns"])
        assert "Local pattern" in all_text  # Local pattern preserved
        assert "storytelling" in all_text or "inspirational" in all_text  # IC hint present

    @patch("packages.core.services.local_intelligence.console")
    def test_blend_with_no_ic_signals_returns_unchanged(self, mock_console):
        """If no IC signals available, local result should be unchanged."""
        from packages.core.services.local_intelligence import LocalIntelligenceService

        svc = LocalIntelligenceService.__new__(LocalIntelligenceService)
        svc._supabase = MagicMock()

        # Mock context
        ctx_result = MagicMock()
        ctx_result.data = {"preferences": {}, "content_niche": ""}

        # Mock empty IC signals
        ic_result = MagicMock()
        ic_result.data = []

        def mock_table(name):
            mock_t = MagicMock()
            mock_s = MagicMock()
            mock_t.select.return_value = mock_s
            mock_eq1 = MagicMock()
            mock_s.eq.return_value = mock_eq1

            if name == "profiles":
                mock_single = MagicMock()
                mock_eq1.single.return_value = mock_single
                mock_single.execute.return_value = ctx_result
            elif name == "ic_signals":
                mock_eq1.eq.return_value = mock_eq1
                mock_eq1.gte.return_value = mock_eq1
                mock_eq1.order.return_value = mock_eq1
                mock_eq1.limit.return_value = mock_eq1
                mock_eq1.execute.return_value = ic_result

            return mock_t

        svc._supabase.table = mock_table

        local_result = {
            "high_retention_patterns": ["Only local"],
            "preferred_clip_formats": [],
            "based_on_runs": 50,
            "mode": "basic",
        }

        blended = svc._blend_with_ic(local_result, "pro-user-123")

        # Should be unchanged
        assert blended["high_retention_patterns"] == ["Only local"]
        assert "ic_signals_count" not in blended


# ─── Raw Signals Never Leak ────────────────────────────────────────────────

class TestNoRawSignalLeakage:
    """Verify that raw signal data (premium, adoption, pattern JSONB) never appears in hints."""

    def test_hints_contain_no_numeric_metrics(self):
        from packages.core.services.local_intelligence import LocalIntelligenceService

        signals = [{
            "signal_type": "clip_hook",
            "pattern": {"hook_type": "question"},
            "performance_premium": 6.66,
            "adoption_rate": 0.27,
            "confidence": 0.8,
            "saturation": "emerging",
        }]

        hints = LocalIntelligenceService._signals_to_hints(signals)
        assert len(hints) == 1
        # Raw metrics should NOT appear in the hint
        assert "6.66" not in hints[0]
        assert "0.27" not in hints[0]
        assert "emerging" not in hints[0]
        assert "performance_premium" not in hints[0]
