"""Media input utilities — detect file paths in text and create Agno media objects."""

import re
from pathlib import Path
from typing import Any

from agno.media import Audio, File, Image, Video

# ── Extension → media type mapping ────────────────────────────────────

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tiff", ".svg"}
AUDIO_EXTENSIONS = {".mp3", ".wav", ".ogg", ".flac", ".aac", ".m4a", ".wma"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".webm", ".mkv", ".wmv"}
DOCUMENT_EXTENSIONS = {
    ".pdf",
    ".docx",
    ".txt",
    ".html",
    ".xml",
    ".csv",
    ".rtf",
    ".json",
    ".py",
    ".js",
    ".ts",
    ".css",
    ".md",
    ".yaml",
    ".yml",
    ".toml",
    ".ini",
    ".cfg",
    ".conf",
    ".log",
    ".sh",
    ".bash",
    ".rb",
    ".go",
    ".rs",
    ".java",
    ".c",
    ".cpp",
    ".h",
    ".hpp",
}

ALL_MEDIA_EXTENSIONS = IMAGE_EXTENSIONS | AUDIO_EXTENSIONS | VIDEO_EXTENSIONS | DOCUMENT_EXTENSIONS

# Build regex alternation from all known extensions (without the dot)
_EXT_ALT = "|".join(ext.lstrip(".") for ext in sorted(ALL_MEDIA_EXTENSIONS))

_URL_PATTERN = re.compile(rf"(https?://\S+\.(?:{_EXT_ALT})(?:\?\S*)?)", re.IGNORECASE)
_FILE_PATTERN = re.compile(rf"(?:^|\s)((?:[~/.]|\w:)[^\s]*\.(?:{_EXT_ALT}))", re.IGNORECASE)


class ParsedMedia:
    """Result of parsing media references from text."""

    __slots__ = ("images", "audio", "videos", "files")

    def __init__(self) -> None:
        self.images: list[Image] = []
        self.audio: list[Audio] = []
        self.videos: list[Video] = []
        self.files: list[File] = []

    @property
    def has_media(self) -> bool:
        return bool(self.images or self.audio or self.videos or self.files)

    def as_kwargs(self) -> dict[str, list[Any]]:
        """Return non-empty media lists as kwargs for team.arun()."""
        kw: dict[str, list[Any]] = {}
        if self.images:
            kw["images"] = self.images
        if self.audio:
            kw["audio"] = self.audio
        if self.videos:
            kw["videos"] = self.videos
        if self.files:
            kw["files"] = self.files
        return kw

    def merge(self, other: "ParsedMedia") -> None:
        """Merge another ParsedMedia into this one."""
        self.images.extend(other.images)
        self.audio.extend(other.audio)
        self.videos.extend(other.videos)
        self.files.extend(other.files)

    @property
    def count(self) -> int:
        return len(self.images) + len(self.audio) + len(self.videos) + len(self.files)

    def summary(self) -> str:
        """Human-readable summary of attached media."""
        parts = []
        if self.images:
            parts.append(f"{len(self.images)} image(s)")
        if self.audio:
            parts.append(f"{len(self.audio)} audio")
        if self.videos:
            parts.append(f"{len(self.videos)} video(s)")
        if self.files:
            parts.append(f"{len(self.files)} file(s)")
        return ", ".join(parts)


def _classify_extension(ext: str) -> str:
    """Return media type for a file extension."""
    ext = ext.lower()
    if ext in IMAGE_EXTENSIONS:
        return "image"
    if ext in AUDIO_EXTENSIONS:
        return "audio"
    if ext in VIDEO_EXTENSIONS:
        return "video"
    if ext in DOCUMENT_EXTENSIONS:
        return "document"
    return "unknown"


def _add_file(media: ParsedMedia, filepath: Path) -> None:
    """Add a local file to the appropriate media list."""
    kind = _classify_extension(filepath.suffix)
    if kind == "image":
        media.images.append(Image(filepath=filepath))
    elif kind == "audio":
        media.audio.append(Audio(filepath=filepath))
    elif kind == "video":
        media.videos.append(Video(filepath=filepath))
    elif kind == "document":
        media.files.append(File(filepath=filepath))


def _add_url(media: ParsedMedia, url: str) -> None:
    """Add a URL to the appropriate media list based on its extension."""
    # Extract extension from URL (before query string)
    path_part = url.split("?")[0]
    ext = Path(path_part).suffix.lower()
    kind = _classify_extension(ext)
    if kind == "image":
        media.images.append(Image(url=url))
    elif kind == "audio":
        media.audio.append(Audio(url=url))
    elif kind == "video":
        media.videos.append(Video(url=url))
    elif kind == "document":
        media.files.append(File(url=url))


def parse_media_from_text(text: str) -> tuple[str, ParsedMedia]:
    """Extract media URLs and file paths from message text.

    Returns (cleaned_text, parsed_media). Referenced files that don't
    exist are left in the text untouched.
    """
    media = ParsedMedia()
    to_remove: list[str] = []

    # URLs
    for match in _URL_PATTERN.finditer(text):
        url = match.group(1)
        _add_url(media, url)
        to_remove.append(url)

    # File paths
    for match in _FILE_PATTERN.finditer(text):
        raw = match.group(1)
        resolved = Path(raw).expanduser().resolve()
        if resolved.is_file():
            _add_file(media, resolved)
            to_remove.append(raw)

    cleaned = text
    for token in to_remove:
        cleaned = cleaned.replace(token, "").strip()
    cleaned = re.sub(r"  +", " ", cleaned).strip()

    return cleaned, media
