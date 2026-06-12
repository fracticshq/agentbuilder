"""Shared document chunking for all knowledge ingestion paths.

Both upload surfaces — the Knowledge Base page (knowledge_service) and the Agent
Wizard (ingestion_service) — chunk through this module so the same agent gets
identical chunks regardless of which upload button was used.

Units: ``chunk_size`` and ``chunk_overlap`` are measured in characters. The
agent's ``configuration.rag.chunking`` values (set in the Agent Wizard) are
interpreted the same way.

Chunking strategy: paragraph-aware packing. Paragraphs are kept whole and packed
into chunks up to ``chunk_size`` characters; a tail of the previous chunk (up to
``chunk_overlap`` characters, snapped to a word boundary) is carried into the
next chunk so sentences spanning a boundary stay retrievable. A single paragraph
longer than ``chunk_size`` is split on the character window as a fallback.
"""

from __future__ import annotations

from typing import List, Optional, Tuple

import structlog

from ..connections import connection_manager

logger = structlog.get_logger(__name__)

DEFAULT_CHUNK_SIZE = 2000   # characters (~500 tokens)
DEFAULT_CHUNK_OVERLAP = 200  # characters

MIN_CHUNK_SIZE = 200
MAX_CHUNK_SIZE = 8000


def clamp_chunking(chunk_size: int, chunk_overlap: int) -> Tuple[int, int]:
    """Clamp chunk parameters to safe bounds (overlap < half the chunk)."""
    size = max(MIN_CHUNK_SIZE, min(MAX_CHUNK_SIZE, int(chunk_size)))
    overlap = max(0, min(size // 2, int(chunk_overlap)))
    return size, overlap


async def resolve_agent_chunking(
    agent_id: Optional[str],
    *,
    default_size: int = DEFAULT_CHUNK_SIZE,
    default_overlap: int = DEFAULT_CHUNK_OVERLAP,
) -> Tuple[int, int]:
    """Resolve chunk size/overlap from the agent's ``rag.chunking`` config.

    Falls back to the shared defaults when the agent is unknown, has no chunking
    config, or the lookup fails (ingestion must not die on a config read).
    """
    chunk_size, chunk_overlap = default_size, default_overlap
    if agent_id:
        try:
            system_db = connection_manager.get_system_db()
            agent = await system_db["agents"].find_one({"id": agent_id})
            chunking = (((agent or {}).get("configuration") or {}).get("rag") or {}).get("chunking") or {}
            if chunking.get("chunk_size"):
                chunk_size = int(chunking["chunk_size"])
            if chunking.get("chunk_overlap") is not None:
                chunk_overlap = int(chunking["chunk_overlap"])
        except Exception as e:
            logger.warning("agent_chunking_config_lookup_failed", agent_id=agent_id, error=str(e))
    return clamp_chunking(chunk_size, chunk_overlap)


def _overlap_tail(chunk: str, overlap: int) -> str:
    """Last ``overlap`` characters of a chunk, snapped forward to a word boundary."""
    if overlap <= 0 or len(chunk) <= overlap:
        return ""
    tail = chunk[-overlap:]
    space = tail.find(" ")
    if 0 <= space < len(tail) - 1:
        tail = tail[space + 1:]
    return tail.strip()


def _split_long_paragraph(paragraph: str, chunk_size: int, chunk_overlap: int) -> List[str]:
    """Character-window fallback for a single paragraph longer than chunk_size."""
    step = max(1, chunk_size - chunk_overlap)
    pieces = []
    start = 0
    while start < len(paragraph):
        piece = paragraph[start:start + chunk_size].strip()
        if piece:
            pieces.append(piece)
        start += step
    return pieces


def chunk_text(
    text: str,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    chunk_overlap: int = DEFAULT_CHUNK_OVERLAP,
) -> List[str]:
    """Paragraph-aware chunking with overlap. Always returns at least one chunk
    for non-empty input."""
    chunk_size, chunk_overlap = clamp_chunking(chunk_size, chunk_overlap)

    if not text or not text.strip():
        return []

    chunks: List[str] = []
    current: List[str] = []
    current_length = 0

    def flush() -> None:
        nonlocal current, current_length
        if current:
            chunks.append("\n\n".join(current))
            current = []
            current_length = 0

    for paragraph in text.split("\n\n"):
        paragraph = paragraph.strip()
        if not paragraph:
            continue

        if len(paragraph) > chunk_size:
            flush()
            chunks.extend(_split_long_paragraph(paragraph, chunk_size, chunk_overlap))
            continue

        if current and current_length + len(paragraph) > chunk_size:
            flush()
            tail = _overlap_tail(chunks[-1], chunk_overlap) if chunks else ""
            if tail:
                current = [tail]
                current_length = len(tail)

        current.append(paragraph)
        current_length += len(paragraph) + 2  # account for the joiner

    flush()

    if not chunks:
        chunks = [text.strip()]

    return chunks
