"""Pure filesystem-like path helpers for knowledge-base metadata."""

from __future__ import annotations

import re
from typing import Optional


def normalize_folder_path(path: Optional[str]) -> str:
    """Normalize a folder path while preserving the root-folder convention."""
    raw_path = (path or "/").strip()
    if not raw_path:
        raw_path = "/"
    if not raw_path.startswith("/"):
        raw_path = f"/{raw_path}"
    normalized = re.sub(r"/+", "/", raw_path).rstrip("/")
    return normalized or "/"


def normalize_item_path(folder: Optional[str], name: Optional[str]) -> tuple[str, str, str]:
    """Return normalized folder, item name, and the item's absolute path."""
    clean_folder = normalize_folder_path(folder)
    clean_name = (name or "untitled").strip().strip("/") or "untitled"
    path = f"{clean_folder.rstrip('/')}/{clean_name}" if clean_folder != "/" else f"/{clean_name}"
    return clean_folder, clean_name, path


def folder_path_from_name(name: Optional[str], parent_path: Optional[str] = None) -> str:
    """Build a normalized folder path from a name and optional parent path."""
    _, clean_name, path = normalize_item_path(parent_path, name)
    return path if clean_name else normalize_folder_path(parent_path)
