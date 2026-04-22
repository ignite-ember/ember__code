"""Media input utilities — detect file paths and resolve references.

Two modes:
1. **Path resolution** (active) — resolves bare filenames and relative paths
   to absolute paths so the AI can use Read or other tools.
2. **Media attachment** (disabled) — detects media files and creates Agno
   media objects for multimodal models. Commented out until vision-capable
   models are supported.
"""

import re
from pathlib import Path
from typing import Any

from agno.media import Audio, File, Image, Video

# ── Extension → media type mapping ────────────────────────────────────

IMAGE_EXTENSIONS = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".bmp",
    ".tiff",
    ".tif",
    ".svg",
    ".avif",
    ".heic",
    ".heif",
}
AUDIO_EXTENSIONS = {".mp3", ".wav", ".ogg", ".flac", ".aac", ".m4a", ".wma"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".webm", ".mkv", ".wmv"}
DOCUMENT_EXTENSIONS = {".pdf"}

ALL_MEDIA_EXTENSIONS = IMAGE_EXTENSIONS | AUDIO_EXTENSIONS | VIDEO_EXTENSIONS | DOCUMENT_EXTENSIONS

# Build regex alternation from all known extensions (without the dot)
_EXT_ALT = "|".join(ext.lstrip(".") for ext in sorted(ALL_MEDIA_EXTENSIONS))

_URL_PATTERN = re.compile(rf"(https?://\S+/\S+\.(?:{_EXT_ALT})(?:\?\S*)?)", re.IGNORECASE)
# Explicit paths (starts with ~, ., /, or drive letter)
_FILE_PATTERN = re.compile(rf"(?:^|\s)((?:[~/.]|\w:)[^\s]*\.(?:{_EXT_ALT}))(?:\s|$)", re.IGNORECASE)
# Bare filenames without a path prefix (e.g. "photo.avif", "report.pdf")
_BARE_FILE_PATTERN = re.compile(rf"(?:^|\s)([^\s/~.][^\s]*\.(?:{_EXT_ALT}))(?:\s|$)", re.IGNORECASE)

# Common directories to search when a bare filename is found
_SEARCH_DIRS = [
    Path.home() / "Downloads",
    Path.home() / "Desktop",
    Path.home() / "Documents",
    Path.home(),
]


# ── Helpers ───────────────────────────────────────────────────────────


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


# ── Path resolution ──────────────────────────────────────────────────


def _find_bare_file(filename: str, project_dir: Path | None = None) -> Path | None:
    """Search common directories for a bare filename.

    Checks the project directory first, then Downloads, Desktop,
    Documents, and home. Returns the first match or None.
    """
    candidates = []
    if project_dir:
        candidates.append(project_dir)
    candidates.extend(_SEARCH_DIRS)

    for directory in candidates:
        candidate = directory / filename
        if candidate.is_file():
            return candidate.resolve()
    return None


def resolve_file_references(text: str, project_dir: Path | None = None) -> tuple[str, list[str]]:
    """Resolve file references in user text to absolute paths.

    Replaces bare filenames and relative paths with their resolved
    absolute paths so the AI can use Read or other tools on them.

    Returns (updated_text, list_of_resolved_paths).
    """
    resolved: list[str] = []

    # Explicit paths (~/..., ./..., /..., C:\\...)
    for match in _FILE_PATTERN.finditer(text):
        raw = match.group(1)
        path = Path(raw).expanduser().resolve()
        if path.is_file() and str(path) != raw:
            text = text.replace(raw, str(path))
            resolved.append(str(path))

    # Bare filenames — search common locations
    for match in _BARE_FILE_PATTERN.finditer(text):
        filename = match.group(1)
        found = _find_bare_file(filename, project_dir)
        if found:
            text = text.replace(filename, str(found))
            resolved.append(str(found))

    return text, resolved


def attach_resolved_files(paths: list[str]) -> dict[str, list[Any]] | None:
    """Convert resolved file paths to Agno media kwargs for vision models.

    Returns a dict like ``{"images": [Image(...)], "files": [File(...)]}``
    suitable for passing to ``team.arun(**kwargs)``, or None if no
    attachable media was found.
    """
    images: list[Image] = []
    audio: list[Audio] = []
    videos: list[Video] = []
    files: list[File] = []

    for path_str in paths:
        p = Path(path_str)
        kind = _classify_extension(p.suffix)
        if kind == "image":
            images.append(Image(filepath=p))
        elif kind == "audio":
            audio.append(Audio(filepath=p))
        elif kind == "video":
            videos.append(Video(filepath=p))
        elif kind == "document":
            files.append(File(filepath=p))

    kw: dict[str, list[Any]] = {}
    if images:
        kw["images"] = images
    if audio:
        kw["audio"] = audio
    if videos:
        kw["videos"] = videos
    if files:
        kw["files"] = files
    return kw or None


def extract_media_urls(text: str) -> dict[str, list[Any]] | None:
    """Extract media URLs from text and return as Agno media kwargs.

    For vision-capable models — attaches remote images, audio, video,
    and documents found in the message text.
    """
    images: list[Image] = []
    audio: list[Audio] = []
    videos: list[Video] = []
    files: list[File] = []

    for match in _URL_PATTERN.finditer(text):
        url = match.group(1)
        path_part = url.split("?")[0]
        ext = Path(path_part).suffix.lower()
        kind = _classify_extension(ext)
        if kind == "image":
            images.append(Image(url=url))
        elif kind == "audio":
            audio.append(Audio(url=url))
        elif kind == "video":
            videos.append(Video(url=url))
        elif kind == "document":
            files.append(File(url=url))

    kw: dict[str, list[Any]] = {}
    if images:
        kw["images"] = images
    if audio:
        kw["audio"] = audio
    if videos:
        kw["videos"] = videos
    if files:
        kw["files"] = files
    return kw or None
