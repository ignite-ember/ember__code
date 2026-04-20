"""Tests for auth/client.py — browser-based CLI authentication."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ember_code.core.auth.client import (
    _CallbackHandler,
    _find_free_port,
    get_login_url,
    start_callback_server,
    validate_token,
)


class TestGetLoginUrl:
    def test_default_portal(self):
        url = get_login_url(9999)
        assert "ignite-ember.sh" in url
        assert "cli-auth" in url
        assert "port=9999" in url

    def test_custom_portal(self):
        url = get_login_url(9999, "https://portal.test.com")
        assert url == "https://portal.test.com/cli-auth?port=9999"

    def test_strips_trailing_slash(self):
        url = get_login_url(9999, "https://portal.test.com/")
        assert url == "https://portal.test.com/cli-auth?port=9999"


class TestFindFreePort:
    def test_returns_int(self):
        port = _find_free_port()
        assert isinstance(port, int)
        assert port > 0

    def test_returns_different_ports(self):
        ports = {_find_free_port() for _ in range(5)}
        # At least some should be different (OS may reuse, but unlikely all same)
        assert len(ports) >= 2


class TestStartCallbackServer:
    def test_returns_server_and_url(self):
        server, callback_url = start_callback_server()
        try:
            assert "localhost" in callback_url
            assert "/callback" in callback_url
            assert _CallbackHandler.token is None
        finally:
            server.server_close()


class TestValidateToken:
    @pytest.mark.asyncio
    async def test_valid_token_returns_user_info(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"email": "user@test.com", "name": "Test User"}

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock()

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await validate_token("valid-token", "https://api.test.com")

        assert result is not None
        assert result["email"] == "user@test.com"

    @pytest.mark.asyncio
    async def test_invalid_token_returns_none(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 401

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock()

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await validate_token("bad-token", "https://api.test.com")

        assert result is None

    @pytest.mark.asyncio
    async def test_network_error_returns_none(self):
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=Exception("connection refused"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock()

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await validate_token("token", "https://api.test.com")

        assert result is None
