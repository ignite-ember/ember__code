"""Enums shared across the code_index package."""

from __future__ import annotations

from enum import StrEnum


class FileSystemType(StrEnum):
    FOLDER = "folder"
    FILE = "file"


class ReferenceTagOperation(StrEnum):
    SET = "set"
    ADD = "add"
    REMOVE = "remove"
