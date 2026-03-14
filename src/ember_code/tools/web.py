"""Web tools — URL fetching and content extraction."""

import httpx
from agno.tools import Toolkit


class WebTools(Toolkit):
    """Fetch and extract content from URLs."""

    def __init__(self):
        super().__init__(name="ember_web")
        self.register(self.fetch_url)
        self.register(self.fetch_json)

    def fetch_url(self, url: str, max_length: int = 10000) -> str:
        """Fetch URL content and extract text.

        Args:
            url: The URL to fetch.
            max_length: Maximum content length to return.

        Returns:
            Extracted text content from the URL.
        """
        try:
            with httpx.Client(timeout=30, follow_redirects=True) as client:
                response = client.get(url, headers={"User-Agent": "EmberCode/0.1.0"})
                response.raise_for_status()

                content_type = response.headers.get("content-type", "")

                if "json" in content_type:
                    return response.text[:max_length]

                # For HTML, do basic text extraction
                text = response.text
                if "html" in content_type:
                    text = self._extract_text_from_html(text)

                return text[:max_length]
        except httpx.HTTPError as e:
            return f"Error fetching {url}: {e}"
        except Exception as e:
            return f"Error: {e}"

    def fetch_json(self, url: str) -> str:
        """Fetch and return JSON from a URL.

        Args:
            url: The URL to fetch JSON from.

        Returns:
            JSON string or error message.
        """
        try:
            with httpx.Client(timeout=30, follow_redirects=True) as client:
                response = client.get(
                    url,
                    headers={
                        "User-Agent": "EmberCode/0.1.0",
                        "Accept": "application/json",
                    },
                )
                response.raise_for_status()
                return response.text[:20000]
        except httpx.HTTPError as e:
            return f"Error fetching {url}: {e}"
        except Exception as e:
            return f"Error: {e}"

    @staticmethod
    def _extract_text_from_html(html: str) -> str:
        """Basic HTML to text extraction."""
        import re

        # Remove script and style tags
        text = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL)
        text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL)
        # Remove HTML tags
        text = re.sub(r"<[^>]+>", " ", text)
        # Clean up whitespace
        text = re.sub(r"\s+", " ", text).strip()
        return text
