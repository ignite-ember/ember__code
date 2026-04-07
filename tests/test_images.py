"""Tests for ember_code.utils.media — media parsing and creation utilities."""

from ember_code.utils.media import ParsedMedia, parse_media_from_text


class TestParseMediaFromText:
    # ── Images ──────────────────────────────────────────────────────

    def test_image_url(self):
        text = "Look at https://example.com/photo.png please"
        cleaned, media = parse_media_from_text(text)
        assert cleaned == "Look at please"
        assert len(media.images) == 1
        assert media.images[0].url == "https://example.com/photo.png"

    def test_image_url_with_query(self):
        text = "Check https://cdn.example.com/img.jpg?w=100&h=200"
        _, media = parse_media_from_text(text)
        assert len(media.images) == 1
        assert "w=100" in media.images[0].url

    def test_image_file(self, tmp_path):
        img = tmp_path / "test.png"
        img.write_bytes(b"fake png")
        text = f"Analyze {img}"
        cleaned, media = parse_media_from_text(text)
        assert len(media.images) == 1
        assert media.images[0].filepath is not None

    # ── Audio ───────────────────────────────────────────────────────

    def test_audio_url(self):
        text = "Listen to https://example.com/song.mp3"
        cleaned, media = parse_media_from_text(text)
        assert len(media.audio) == 1
        assert media.audio[0].url == "https://example.com/song.mp3"

    def test_audio_file(self, tmp_path):
        f = tmp_path / "recording.wav"
        f.write_bytes(b"fake wav")
        text = f"Transcribe {f}"
        _, media = parse_media_from_text(text)
        assert len(media.audio) == 1

    # ── Video ──────────────────────────────────────────────────────

    def test_video_url(self):
        text = "Watch https://example.com/clip.mp4"
        _, media = parse_media_from_text(text)
        assert len(media.videos) == 1

    def test_video_file(self, tmp_path):
        f = tmp_path / "demo.mov"
        f.write_bytes(b"fake mov")
        text = f"Analyze {f}"
        _, media = parse_media_from_text(text)
        assert len(media.videos) == 1

    # ── Documents ──────────────────────────────────────────────────

    def test_pdf_url(self):
        text = "Read https://example.com/report.pdf"
        _, media = parse_media_from_text(text)
        assert len(media.files) == 1

    def test_pdf_file(self, tmp_path):
        f = tmp_path / "doc.pdf"
        f.write_bytes(b"fake pdf")
        text = f"Summarize {f}"
        _, media = parse_media_from_text(text)
        assert len(media.files) == 1

    def test_python_file(self, tmp_path):
        f = tmp_path / "script.py"
        f.write_text("print('hi')")
        text = f"Review {f}"
        _, media = parse_media_from_text(text)
        assert len(media.files) == 1

    # ── Mixed and edge cases ──────────────────────────────────────

    def test_mixed_media(self, tmp_path):
        img = tmp_path / "photo.png"
        img.write_bytes(b"img")
        pdf = tmp_path / "doc.pdf"
        pdf.write_bytes(b"pdf")
        text = f"Compare {img} with {pdf} and https://example.com/song.mp3"
        _, media = parse_media_from_text(text)
        assert len(media.images) == 1
        assert len(media.files) == 1
        assert len(media.audio) == 1
        assert media.count == 3

    def test_nonexistent_file_left_in_text(self):
        text = "Look at /nonexistent/path/image.png"
        cleaned, media = parse_media_from_text(text)
        assert not media.has_media
        assert "/nonexistent/path/image.png" in cleaned

    def test_no_media(self):
        text = "Just a regular message"
        cleaned, media = parse_media_from_text(text)
        assert cleaned == text
        assert not media.has_media

    def test_collapse_whitespace(self):
        text = "Before https://example.com/img.png after"
        cleaned, _ = parse_media_from_text(text)
        assert "  " not in cleaned


class TestParsedMedia:
    def test_as_kwargs_empty(self):
        media = ParsedMedia()
        assert media.as_kwargs() == {}

    def test_summary(self):
        media = ParsedMedia()
        from agno.media import Audio, Image

        media.images.append(Image(url="https://x.com/a.png"))
        media.audio.append(Audio(url="https://x.com/a.mp3"))
        assert "1 image(s)" in media.summary()
        assert "1 audio" in media.summary()

    def test_merge(self):
        a = ParsedMedia()
        b = ParsedMedia()
        from agno.media import Image

        a.images.append(Image(url="https://x.com/1.png"))
        b.images.append(Image(url="https://x.com/2.png"))
        a.merge(b)
        assert len(a.images) == 2
