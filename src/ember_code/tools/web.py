"""Web tools — URL fetching and content extraction."""

import re

import httpx
from agno.tools import Toolkit


class WebTools(Toolkit):
    """Fetch and extract content from URLs."""

    def __init__(self, **kwargs):
        super().__init__(name="ember_web", **kwargs)
        self.register(self.fetch_url)
        self.register(self.fetch_json)

    async def fetch_url(self, url: str, max_length: int = 10000) -> str:
        """Fetch URL content and extract text.

        Args:
            url: The URL to fetch.
            max_length: Maximum content length to return.

        Returns:
            Extracted text content from the URL.
        """
        try:
            async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
                response = await client.get(url, headers={"User-Agent": "EmberCode/0.1.0"})
                response.raise_for_status()

                content_type = response.headers.get("content-type", "")

                if "json" in content_type:
                    return response.text[:max_length]

                text = response.text
                if "html" in content_type:
                    text = _extract_text_from_html(text)

                return text[:max_length]
        except httpx.HTTPError as e:
            return f"Error fetching {url}: {e}"
        except Exception as e:
            return f"Error: {e}"

    async def fetch_json(self, url: str) -> str:
        """Fetch and return JSON from a URL.

        Args:
            url: The URL to fetch JSON from.

        Returns:
            JSON string or error message.
        """
        try:
            async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
                response = await client.get(
                    url,
                    headers={"User-Agent": "EmberCode/0.1.0", "Accept": "application/json"},
                )
                response.raise_for_status()
                return response.text[:20000]
        except httpx.HTTPError as e:
            return f"Error fetching {url}: {e}"
        except Exception as e:
            return f"Error: {e}"


def _extract_text_from_html(html: str) -> str:
    """Basic HTML to text extraction."""
    text = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL)
    text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text
