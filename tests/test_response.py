"""Tests for utils/response.py — response text extraction."""

from unittest.mock import MagicMock

from ember_code.core.utils.response import extract_response_text


class TestExtractResponseText:
    def test_extracts_content_string(self):
        response = MagicMock()
        response.content = "Hello, world!"
        assert extract_response_text(response) == "Hello, world!"

    def test_extracts_from_none_content(self):
        response = MagicMock()
        response.content = None
        result = extract_response_text(response)
        assert isinstance(result, str)

    def test_handles_string_response(self):
        # If response is just a string
        result = extract_response_text("plain string")
        assert isinstance(result, str)

    def test_handles_no_content_attr(self):
        response = MagicMock(spec=[])  # no attributes
        result = extract_response_text(response)
        assert isinstance(result, str)
