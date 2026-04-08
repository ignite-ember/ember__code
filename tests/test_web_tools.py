"""Tests for tools/web.py — web fetch tools."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ember_code.tools.web import WebTools, _extract_text_from_html


class TestWebTools:
    def test_registers_functions(self):
        tools = WebTools()
        names = {f.name for f in tools.functions.values()} | {
            f.name for f in tools.async_functions.values()
        }
        assert "fetch_url" in names
        assert "fetch_json" in names

    def test_extract_text_from_html(self):
        html = "<html><body><h1>Title</h1><p>Hello world</p><script>bad();</script></body></html>"
        text = _extract_text_from_html(html)
        assert "Title" in text
        assert "Hello world" in text
        assert "bad()" not in text

    @pytest.mark.asyncio
    async def test_fetch_url_success(self):
        tools = WebTools()
        mock_response = MagicMock()
        mock_response.text = "<html><body>Hello</body></html>"
        mock_response.headers = {"content-type": "text/html"}
        mock_response.raise_for_status = MagicMock()

        with patch("ember_code.tools.web.httpx.AsyncClient") as MockClient:
            instance = AsyncMock()
            instance.get = AsyncMock(return_value=mock_response)
            instance.__aenter__ = AsyncMock(return_value=instance)
            instance.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = instance

            result = await tools.fetch_url("https://example.com")
            assert "Hello" in result

    @pytest.mark.asyncio
    async def test_fetch_url_truncates(self):
        tools = WebTools()
        mock_response = MagicMock()
        mock_response.text = "x" * 20000
        mock_response.headers = {"content-type": "text/plain"}
        mock_response.raise_for_status = MagicMock()

        with patch("ember_code.tools.web.httpx.AsyncClient") as MockClient:
            instance = AsyncMock()
            instance.get = AsyncMock(return_value=mock_response)
            instance.__aenter__ = AsyncMock(return_value=instance)
            instance.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = instance

            result = await tools.fetch_url("https://example.com", max_length=100)
            assert len(result) <= 100

    @pytest.mark.asyncio
    async def test_fetch_json_success(self):
        tools = WebTools()
        mock_response = MagicMock()
        mock_response.text = '{"key": "value"}'
        mock_response.headers = {"content-type": "application/json"}
        mock_response.raise_for_status = MagicMock()

        with patch("ember_code.tools.web.httpx.AsyncClient") as MockClient:
            instance = AsyncMock()
            instance.get = AsyncMock(return_value=mock_response)
            instance.__aenter__ = AsyncMock(return_value=instance)
            instance.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = instance

            result = await tools.fetch_json("https://api.example.com/data")
            assert "key" in result

    @pytest.mark.asyncio
    async def test_fetch_url_error(self):
        tools = WebTools()

        with patch("ember_code.tools.web.httpx.AsyncClient") as MockClient:
            instance = AsyncMock()
            instance.get = AsyncMock(side_effect=Exception("connection refused"))
            instance.__aenter__ = AsyncMock(return_value=instance)
            instance.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = instance

            result = await tools.fetch_url("https://bad.example.com")
            assert "Error" in result
