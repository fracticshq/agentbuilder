"""Tests for the shared chunking module used by both upload paths.

The point of app/services/chunking.py is that the Knowledge Base page and the
Agent Wizard produce identical chunks for the same agent. These tests cover the
chunker itself, agent-config resolution, and the cross-path consistency.
"""

from __future__ import annotations

from copy import deepcopy

import pytest

from app.services import chunking
from app.services.chunking import (
    DEFAULT_CHUNK_OVERLAP,
    DEFAULT_CHUNK_SIZE,
    MAX_CHUNK_SIZE,
    MIN_CHUNK_SIZE,
    chunk_text,
    clamp_chunking,
    resolve_agent_chunking,
)


# ── chunk_text ────────────────────────────────────────────────────────────

def test_empty_text_returns_no_chunks():
    assert chunk_text("") == []
    assert chunk_text("   \n\n  ") == []


def test_short_text_is_single_chunk():
    text = "One short paragraph."
    assert chunk_text(text) == [text]


def test_paragraphs_pack_up_to_chunk_size():
    paragraphs = [f"Paragraph {i} " + "x" * 80 for i in range(10)]
    text = "\n\n".join(paragraphs)
    chunks = chunk_text(text, chunk_size=300, chunk_overlap=0)
    assert len(chunks) > 1
    for chunk in chunks:
        assert len(chunk) <= 300
    # No paragraph content is lost.
    joined = "\n\n".join(chunks)
    for i in range(10):
        assert f"Paragraph {i} " in joined


def test_overlap_carries_tail_into_next_chunk():
    paragraphs = ["alpha " * 30, "bravo " * 30, "charlie " * 30]
    text = "\n\n".join(p.strip() for p in paragraphs)
    chunks = chunk_text(text, chunk_size=200, chunk_overlap=60)
    assert len(chunks) >= 2
    # The second chunk starts with a tail of the first (overlap), so boundary
    # content appears in both.
    tail_word = chunks[0].split()[-1]
    assert tail_word in chunks[1]


def test_paragraph_longer_than_chunk_size_is_split():
    long_paragraph = "word " * 500  # ~2500 chars, no \n\n
    chunks = chunk_text(long_paragraph, chunk_size=400, chunk_overlap=50)
    assert len(chunks) > 1
    for chunk in chunks:
        assert len(chunk) <= 400


def test_clamp_bounds():
    size, overlap = clamp_chunking(10, 10_000)
    assert size == MIN_CHUNK_SIZE
    assert overlap == size // 2
    size, overlap = clamp_chunking(1_000_000, -5)
    assert size == MAX_CHUNK_SIZE
    assert overlap == 0


# ── resolve_agent_chunking ────────────────────────────────────────────────

class FakeCollection:
    def __init__(self, documents):
        self.documents = [deepcopy(d) for d in documents]

    async def find_one(self, query):
        for document in self.documents:
            if all(document.get(k) == v for k, v in (query or {}).items()):
                return deepcopy(document)
        return None


class FakeSystemDb:
    def __init__(self, agents):
        self.agents = FakeCollection(agents)

    def __getitem__(self, name):
        return getattr(self, name)


@pytest.mark.asyncio
async def test_resolve_defaults_without_agent():
    assert await resolve_agent_chunking(None) == (DEFAULT_CHUNK_SIZE, DEFAULT_CHUNK_OVERLAP)


@pytest.mark.asyncio
async def test_resolve_uses_agent_rag_chunking(monkeypatch):
    db = FakeSystemDb([{
        "id": "agent-1",
        "configuration": {"rag": {"chunking": {"chunk_size": 800, "chunk_overlap": 100}}},
    }])
    monkeypatch.setattr(chunking.connection_manager, "get_system_db", lambda: db)
    assert await resolve_agent_chunking("agent-1") == (800, 100)


@pytest.mark.asyncio
async def test_resolve_clamps_configured_values(monkeypatch):
    db = FakeSystemDb([{
        "id": "agent-1",
        "configuration": {"rag": {"chunking": {"chunk_size": 50, "chunk_overlap": 9999}}},
    }])
    monkeypatch.setattr(chunking.connection_manager, "get_system_db", lambda: db)
    size, overlap = await resolve_agent_chunking("agent-1")
    assert size == MIN_CHUNK_SIZE
    assert overlap == size // 2


@pytest.mark.asyncio
async def test_resolve_falls_back_on_lookup_failure(monkeypatch):
    def boom():
        raise RuntimeError("db down")
    monkeypatch.setattr(chunking.connection_manager, "get_system_db", boom)
    assert await resolve_agent_chunking("agent-1") == (DEFAULT_CHUNK_SIZE, DEFAULT_CHUNK_OVERLAP)


# ── cross-path consistency ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_both_upload_paths_produce_identical_chunks(monkeypatch):
    """KB-page (knowledge_service) and wizard (ingestion_service) uploads must
    chunk the same document identically for the same agent."""
    from types import SimpleNamespace
    from app.services.ingestion_service import IngestionService
    from app.services.knowledge_service import KnowledgeService

    db = FakeSystemDb([{
        "id": "agent-1",
        "configuration": {"rag": {"chunking": {"chunk_size": 300, "chunk_overlap": 40}}},
    }])
    monkeypatch.setattr(chunking.connection_manager, "get_system_db", lambda: db)

    text = "\n\n".join(f"Paragraph {i} " + "y" * 90 for i in range(8))

    # Knowledge path
    knowledge_service = KnowledgeService.__new__(KnowledgeService)
    knowledge_chunks = await KnowledgeService._chunk_text(knowledge_service, text, "doc.txt", agent_id="agent-1")

    # Ingestion path
    ingestion_service = IngestionService.__new__(IngestionService)
    size, overlap = await IngestionService._resolve_chunking(ingestion_service, "agent-1")
    ingestion_chunk_docs = await IngestionService._extract_and_chunk(
        ingestion_service, text.encode("utf-8"), "text/plain", "doc.txt",
        chunk_size=size, chunk_overlap=overlap,
    )
    ingestion_chunks = [doc["content"] for doc in ingestion_chunk_docs]

    assert knowledge_chunks == ingestion_chunks
