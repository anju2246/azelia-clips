"""
Tests for Security Hardening (Migration 007) — validates auth middleware changes,
JWT verification fix, user_id in ic_user_telemetry, and token encryption support.
"""

import pytest
import time
from unittest.mock import patch, MagicMock, PropertyMock


# ─── Auth Middleware Tests ─────────────────────────────────────────────────────

class TestOptionalAuth:
    """Verify optional_auth never returns a fake user."""

    def _make_credentials(self, token="fake.jwt.token"):
        cred = MagicMock()
        cred.credentials = token
        return cred

    def test_no_credentials_returns_none(self):
        from server.middleware.auth import optional_auth
        result = optional_auth(credentials=None)
        assert result is None

    @patch("server.middleware.auth.verify_supabase_jwt")
    def test_valid_token_returns_verified_user(self, mock_verify):
        mock_verify.return_value = MagicMock(id="real-user", email="a@b.com", role="authenticated")
        from server.middleware.auth import optional_auth
        result = optional_auth(credentials=self._make_credentials("valid.jwt.token"))
        mock_verify.assert_called_once_with("valid.jwt.token")
        assert result.id == "real-user"


class TestRequireOnboarding:
    """Verify onboarding check returns 428 when content_niche is NULL."""

    def _make_credentials(self, token="fake.jwt.token"):
        cred = MagicMock()
        cred.credentials = token
        return cred

    @patch("supabase.create_client")
    @patch("server.middleware.auth.settings")
    @patch("server.middleware.auth.verify_supabase_jwt")
    def test_428_when_niche_is_null(self, mock_verify, mock_settings, mock_create):
        from fastapi import HTTPException
        mock_verify.return_value = MagicMock(id="user-1", email="a@b.com", role="authenticated")
        mock_settings.supabase_url = "https://test.supabase.co"
        mock_settings.supabase_key = "test-key"

        mock_sb = MagicMock()
        mock_create.return_value = mock_sb
        mock_table = MagicMock()
        mock_sb.table.return_value = mock_table
        mock_select = MagicMock()
        mock_table.select.return_value = mock_select
        mock_select.eq.return_value = mock_select
        mock_select.execute.return_value = MagicMock(data=[{"content_niche": None}])

        from server.middleware.auth import require_onboarding
        with pytest.raises(HTTPException) as exc_info:
            require_onboarding(credentials=self._make_credentials())
        assert exc_info.value.status_code == 428

    @patch("supabase.create_client")
    @patch("server.middleware.auth.settings")
    @patch("server.middleware.auth.verify_supabase_jwt")
    def test_passes_when_niche_is_set(self, mock_verify, mock_settings, mock_create):
        mock_verify.return_value = MagicMock(id="user-1", email="a@b.com", role="authenticated")
        mock_settings.supabase_url = "https://test.supabase.co"
        mock_settings.supabase_key = "test-key"

        mock_sb = MagicMock()
        mock_create.return_value = mock_sb
        mock_table = MagicMock()
        mock_sb.table.return_value = mock_table
        mock_select = MagicMock()
        mock_table.select.return_value = mock_select
        mock_select.eq.return_value = mock_select
        mock_select.execute.return_value = MagicMock(data=[{"content_niche": "tech"}])

        from server.middleware.auth import require_onboarding
        result = require_onboarding(credentials=self._make_credentials())
        assert result.id == "user-1"

    @patch("server.middleware.auth.settings")
    def test_401_when_no_credentials(self, mock_settings):
        from fastapi import HTTPException
        from server.middleware.auth import require_onboarding
        with pytest.raises(HTTPException) as exc_info:
            require_onboarding(credentials=None)
        assert exc_info.value.status_code == 401


# ─── JWT Verification Fix in analytics.py ──────────────────────────────────────

class TestGetUserIdFromAuth:
    """Verify _get_user_id_from_auth uses verify_supabase_jwt, not manual decode."""

    @patch("packages.core.auth.verify_supabase_jwt")
    def test_returns_user_id_from_verified_jwt(self, mock_verify):
        mock_verify.return_value = MagicMock(id="verified-user-123")
        from server.routes.analytics import _get_user_id_from_auth
        result = _get_user_id_from_auth("Bearer some.jwt.token")
        assert result == "verified-user-123"
        mock_verify.assert_called_once_with("some.jwt.token")

    def test_returns_none_for_empty_auth(self):
        from server.routes.analytics import _get_user_id_from_auth
        assert _get_user_id_from_auth(None) is None
        assert _get_user_id_from_auth("") is None

    @patch("packages.core.auth.verify_supabase_jwt")
    def test_returns_none_on_verification_failure(self, mock_verify):
        mock_verify.side_effect = Exception("Invalid token")
        from server.routes.analytics import _get_user_id_from_auth
        result = _get_user_id_from_auth("Bearer invalid.token.here")
        assert result is None


# ─── user_id in ic_user_telemetry INSERT ───────────────────────────────────────

class TestUserIdInIcUserTelemetry:
    """Verify track_youtube_performance includes user_id in ic_user_telemetry INSERT."""

    @patch("packages.core.services.telemetry.settings")
    @patch("packages.core.services.telemetry.create_client")
    def test_insert_includes_user_id(self, mock_create, mock_settings):
        mock_settings.azelia_telemetry_enabled = True
        mock_settings.supabase_url = "https://test.supabase.co"
        mock_settings.supabase_key = "test-key"

        mock_sb = MagicMock()
        mock_create.return_value = mock_sb

        from packages.core.services.telemetry import TelemetryService
        svc = TelemetryService()

        captured_data = {}

        def capture_insert(data):
            captured_data.update(data)
            mock_result = MagicMock()
            mock_result.execute.return_value = None
            return mock_result

        mock_table = MagicMock()
        mock_sb.table.return_value = mock_table
        mock_table.insert.side_effect = capture_insert

        # Mock profiles select for episode_format lookup
        mock_select = MagicMock()
        mock_table.select.return_value = mock_select
        mock_select.eq.return_value = mock_select
        mock_select.execute.return_value = MagicMock(
            data=[{"preferences": {"episode_format": "interview"}}]
        )

        test_user_id = "user-abc-123"
        svc.track_youtube_performance(
            user_id=test_user_id,
            youtube_id="vid123",
            views=500,
            likes=20,
            comments=5,
        )

        time.sleep(0.5)

        assert captured_data.get("user_id") == test_user_id, (
            "ic_user_telemetry INSERT must include user_id"
        )


# ─── AnalyticsSync connect_platform ───────────────────────────────────────────

class TestConnectPlatform:
    """Verify connect_platform behavior."""

    def test_connect_platform_disabled_returns_false(self):
        from server.services.analytics import AnalyticsSync
        sync = AnalyticsSync.__new__(AnalyticsSync)
        sync.Enabled = False
        sync.client = None

        result = sync.connect_platform(platform="youtube")
        assert result is False

    def test_connect_platform_inserts_new_connection(self):
        from server.services.analytics import AnalyticsSync
        sync = AnalyticsSync.__new__(AnalyticsSync)
        sync.Enabled = True
        sync.client = MagicMock()

        mock_table = MagicMock()
        sync.client.table.return_value = mock_table
        mock_select = MagicMock()
        mock_table.select.return_value = mock_select
        mock_select.eq.return_value = mock_select
        mock_select.execute.return_value = MagicMock(data=[])

        mock_insert = MagicMock()
        mock_table.insert.return_value = mock_insert
        mock_insert.execute.return_value = None

        result = sync.connect_platform(platform="youtube", metadata={"channel_id": "abc"})

        assert result is True
        insert_call = mock_table.insert.call_args[0][0]
        assert insert_call["platform"] == "youtube"
        assert insert_call["metadata"] == {"channel_id": "abc"}
