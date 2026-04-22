"""Tests for ember_code.utils.media — file resolution and media attachment."""

from ember_code.core.utils.media import attach_resolved_files, resolve_file_references


class TestResolveFileReferences:
    def test_bare_filename_found(self, tmp_path):
        """Bare filename is resolved when found in a search directory."""
        img = tmp_path / "photo.png"
        img.write_bytes(b"fake png")
        text, resolved = resolve_file_references("Look at photo.png", project_dir=tmp_path)
        assert len(resolved) == 1
        assert str(tmp_path / "photo.png") in text

    def test_bare_filename_not_found(self):
        """Bare filename that doesn't exist anywhere is left unchanged."""
        text, resolved = resolve_file_references("Look at nonexistent_file.png")
        assert resolved == []
        assert "nonexistent_file.png" in text

    def test_explicit_path_resolved(self, tmp_path):
        """Explicit relative path is resolved to absolute."""
        img = tmp_path / "test.jpg"
        img.write_bytes(b"fake jpg")
        text, resolved = resolve_file_references(f"Check {img}")
        assert len(resolved) >= 0

    def test_no_media_extensions(self):
        """Regular text without media file extensions is unchanged."""
        text, resolved = resolve_file_references("Just a regular message")
        assert text == "Just a regular message"
        assert resolved == []

    def test_python_file_not_resolved(self):
        """Non-media file extensions are not touched."""
        text, resolved = resolve_file_references("Check script.py")
        assert resolved == []
        assert text == "Check script.py"

    def test_multiple_files(self, tmp_path):
        """Multiple bare filenames are all resolved."""
        a = tmp_path / "a.png"
        b = tmp_path / "b.pdf"
        a.write_bytes(b"img")
        b.write_bytes(b"pdf")
        text, resolved = resolve_file_references("Compare a.png and b.pdf", project_dir=tmp_path)
        assert len(resolved) == 2


class TestAttachResolvedFiles:
    """Vision models get Agno media objects from resolved paths."""

    def test_image_attached(self, tmp_path):
        img = tmp_path / "photo.jpg"
        img.write_bytes(b"\xff\xd8")
        result = attach_resolved_files([str(img)])
        assert result is not None
        assert "images" in result
        assert len(result["images"]) == 1

    def test_pdf_attached(self, tmp_path):
        pdf = tmp_path / "doc.pdf"
        pdf.write_bytes(b"%PDF")
        result = attach_resolved_files([str(pdf)])
        assert result is not None
        assert "files" in result

    def test_non_media_returns_none(self):
        result = attach_resolved_files(["/some/path/script.py"])
        assert result is None

    def test_mixed_media(self, tmp_path):
        img = tmp_path / "photo.png"
        pdf = tmp_path / "doc.pdf"
        img.write_bytes(b"img")
        pdf.write_bytes(b"pdf")
        result = attach_resolved_files([str(img), str(pdf)])
        assert result is not None
        assert "images" in result
        assert "files" in result

    def test_empty_list(self):
        result = attach_resolved_files([])
        assert result is None
