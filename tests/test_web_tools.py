"""Tests for tools/web.py — web fetch tools."""

from unittest.mock import MagicMock, patch

from ember_code.tools.web import WebTools


class TestWebTools:
    def test_registers_functions(self):
        tools = WebTools()
        func_names = [f.name for f in tools.functions.values()]
        assert "fetch_url" in func_names
        assert "fetch_json" in func_names

    def test_extract_text_from_html(self):
        html = "<html><body><h1>Title</h1><p>Hello world</p><script>bad();</script></body></html>"
        text = WebTools._extract_text_from_html(html)
        assert "Title" in text
        assert "Hello world" in text
        assert "bad()" not in text

    def test_extract_text_from_plain(self):
        text = WebTools._extract_text_from_html("Just plain text, no HTML")
        assert "Just plain text" in text

    def test_fetch_url_success(self):
        tools = WebTools()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "<html><body>Hello</body></html>"
        mock_response.headers = {"content-type": "text/html"}
        mock_response.raise_for_status = MagicMock()

        with patch("ember_code.tools.web.httpx.Client") as MockClient:
            instance = MagicMock()
            instance.get.return_value = mock_response
            instance.__enter__ = MagicMock(return_value=instance)
            instance.__exit__ = MagicMock(return_value=False)
            MockClient.return_value = instance

            result = tools.fetch_url("https://example.com")
            assert "Hello" in result

    def test_fetch_url_truncates(self):
        tools = WebTools()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "x" * 20000
        mock_response.headers = {"content-type": "text/plain"}
        mock_response.raise_for_status = MagicMock()

        with patch("ember_code.tools.web.httpx.Client") as MockClient:
            instance = MagicMock()
            instance.get.return_value = mock_response
            instance.__enter__ = MagicMock(return_value=instance)
            instance.__exit__ = MagicMock(return_value=False)
            MockClient.return_value = instance

            result = tools.fetch_url("https://example.com", max_length=100)
            assert len(result) <= 100

    def test_fetch_json_success(self):
        tools = WebTools()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = '{"key": "value"}'
        mock_response.headers = {"content-type": "application/json"}
        mock_response.raise_for_status = MagicMock()

        with patch("ember_code.tools.web.httpx.Client") as MockClient:
            instance = MagicMock()
            instance.get.return_value = mock_response
            instance.__enter__ = MagicMock(return_value=instance)
            instance.__exit__ = MagicMock(return_value=False)
            MockClient.return_value = instance

            result = tools.fetch_json("https://api.example.com/data")
            assert "key" in result
            assert "value" in result
