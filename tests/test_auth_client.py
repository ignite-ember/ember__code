"""Tests for auth/client.py — device-flow authentication."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ember_code.auth.client import poll_for_token, request_device_code


class TestRequestDeviceCode:
    @pytest.mark.asyncio
    async def test_returns_device_code(self):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "device_code": "abc123",
            "login_url": "https://example.com/login",
            "expires_in": 600,
        }
        mock_resp.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock()

        with patch("ember_code.auth.client.httpx.AsyncClient", return_value=mock_client):
            result = await request_device_code("https://api.test.com")

        assert result["device_code"] == "abc123"
        assert "login_url" in result

    @pytest.mark.asyncio
    async def test_uses_correct_url(self):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"device_code": "x"}
        mock_resp.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock()

        with patch("ember_code.auth.client.httpx.AsyncClient", return_value=mock_client):
            await request_device_code("https://api.test.com/")

        call_args = mock_client.post.call_args[0][0]
        assert call_args == "https://api.test.com/v1/auth/device"


class TestPollForToken:
    @pytest.mark.asyncio
    async def test_returns_token_on_200(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "access_token": "tok-abc",
            "email": "user@test.com",
            "model_api_key": "key-123",
            "model_url": "https://model.test.com",
        }

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock()

        with patch("ember_code.auth.client.httpx.AsyncClient", return_value=mock_client):
            result = await poll_for_token("device-code-123", "https://api.test.com")

        assert result["access_token"] == "tok-abc"
        assert result["email"] == "user@test.com"

    @pytest.mark.asyncio
    async def test_polls_on_202_then_succeeds(self):
        pending_resp = MagicMock()
        pending_resp.status_code = 202

        success_resp = MagicMock()
        success_resp.status_code = 200
        success_resp.json.return_value = {"access_token": "tok"}

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=[pending_resp, success_resp])
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock()

        with (
            patch("ember_code.auth.client.httpx.AsyncClient", return_value=mock_client),
            patch("ember_code.auth.client.asyncio.sleep", new_callable=AsyncMock),
        ):
            result = await poll_for_token(
                "dc",
                "https://api.test.com",
                poll_interval=0.01,
                max_poll_time=10,
            )

        assert result["access_token"] == "tok"
        assert mock_client.post.call_count == 2

    @pytest.mark.asyncio
    async def test_timeout_raises(self):
        pending_resp = MagicMock()
        pending_resp.status_code = 202

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=pending_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock()

        with (
            patch("ember_code.auth.client.httpx.AsyncClient", return_value=mock_client),
            patch("ember_code.auth.client.asyncio.sleep", new_callable=AsyncMock),
            pytest.raises(TimeoutError, match="timed out"),
        ):
            await poll_for_token(
                "dc",
                "https://api.test.com",
                poll_interval=0.01,
                max_poll_time=0.02,
            )
