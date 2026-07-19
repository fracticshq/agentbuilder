from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import httpx
import pytest

import app.services.ingestion_service as ingestion_module
from app.config import Settings
from app.services.ingestion_service import IngestionEmbeddingError, IngestionService
from memory.managers.episodic import EpisodicMemory
from memory.processors.pii_vault import PIIVault
from memory.types import EpisodicFact, PIIField
from memory.utils.crypto import CryptoError, CryptoUtils


class _VoyageErrorClient:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False

    async def post(self, *args, **kwargs):
        return httpx.Response(
            401,
            request=httpx.Request("POST", "https://voyage.example/v1/embeddings"),
        )


class _InsertResult:
    def __init__(self, inserted_id):
        self.inserted_id = inserted_id


class _FailingMongoCollection:
    async def insert_one(self, document):
        raise RuntimeError("MongoDB unavailable")


class _SuccessfulMongoCollection:
    def __init__(self):
        self.inserted = []

    async def insert_one(self, document):
        self.inserted.append(document)
        return _InsertResult("mongo-chunk-id")


class _Database:
    def __init__(self, collection):
        self.collection = collection

    def __getitem__(self, name):
        assert name == "knowledge_base"
        return self.collection


class _FailingQdrant:
    async def upsert_chunk(self, chunk, brand_slug):
        raise RuntimeError("Qdrant unavailable")


class _MemoryJobStore:
    """Keep storage-failure tests focused on the knowledge-base write path."""

    def __init__(self):
        self.jobs = {}

    async def set(self, job_id, data):
        self.jobs[job_id] = dict(data)

    async def get(self, job_id):
        job = self.jobs.get(job_id)
        return dict(job) if job else None

    async def update(self, job_id, updates):
        if job_id not in self.jobs:
            return False
        self.jobs[job_id].update(updates)
        return True


def _single_chunk():
    return [{"content": "Sensitive but valid document content", "metadata": {}}]


def _embedding():
    return [0.25] * 1024


async def _prepare_single_file_job(service: IngestionService) -> str:
    service.job_store = _MemoryJobStore()
    service._resolve_chunking = AsyncMock(return_value=(1000, 100))
    service._extract_and_chunk = AsyncMock(return_value=_single_chunk())
    return await service.start_ingestion_job(
        [{"content": b"document", "filename": "document.txt", "content_type": "text/plain"}]
    )


@pytest.mark.asyncio
async def test_voyage_auth_failure_marks_job_error_without_storing_zero_vector(monkeypatch):
    service = IngestionService(Settings(VECTOR_BACKEND="atlas"))
    service._get_voyage_runtime_config = AsyncMock(
        return_value={
            "api_key": "voyage-test-key",
            "base_url": "https://voyage.example/v1",
            "model": "voyage-3-large",
        }
    )
    store_chunk = AsyncMock()
    service._store_chunk = store_chunk
    monkeypatch.setattr(ingestion_module.httpx, "AsyncClient", _VoyageErrorClient)

    job_id = await _prepare_single_file_job(service)
    await service.process_documents(
        job_id,
        [{"content": b"document", "filename": "document.txt", "content_type": "text/plain"}],
    )

    job = await service.job_store.get(job_id)
    assert job["status"] == "error"
    assert job["processed_count"] == 0
    assert job["error"] == "Document embedding failed"
    assert "401" not in job["error"]
    store_chunk.assert_not_awaited()

    with pytest.raises(IngestionEmbeddingError, match="HTTP 401"):
        await service._generate_embeddings("document")


@pytest.mark.asyncio
async def test_mongo_storage_failure_marks_job_error_instead_of_returning_a_fake_id(monkeypatch):
    service = IngestionService(Settings(VECTOR_BACKEND="atlas"))
    service._generate_embeddings = AsyncMock(return_value=_embedding())
    monkeypatch.setattr(
        ingestion_module.connection_manager,
        "get_system_db",
        lambda: _Database(_FailingMongoCollection()),
    )

    job_id = await _prepare_single_file_job(service)
    await service.process_documents(
        job_id,
        [{"content": b"document", "filename": "document.txt", "content_type": "text/plain"}],
    )

    job = await service.job_store.get(job_id)
    assert job["status"] == "error"
    assert job["processed_count"] == 0
    assert job["error"] == "Failed to store knowledge-base document"


@pytest.mark.asyncio
async def test_qdrant_storage_failure_marks_job_error_instead_of_returning_a_fake_id(monkeypatch):
    service = IngestionService(Settings(VECTOR_BACKEND="qdrant"))
    service.qdrant = _FailingQdrant()
    service._generate_embeddings = AsyncMock(return_value=_embedding())
    collection = _SuccessfulMongoCollection()
    monkeypatch.setattr(
        ingestion_module.connection_manager,
        "get_system_db",
        lambda: _Database(collection),
    )

    job_id = await _prepare_single_file_job(service)
    await service.process_documents(
        job_id,
        [{"content": b"document", "filename": "document.txt", "content_type": "text/plain"}],
    )

    job = await service.job_store.get(job_id)
    assert job["status"] == "error"
    assert job["processed_count"] == 0
    assert job["error"] == "Failed to store knowledge-base document"
    assert len(collection.inserted) == 1


def test_pii_encryption_envelope_persists_metadata_and_decrypts():
    vault = PIIVault(
        master_key=CryptoUtils.generate_key(),
        key_id="pii-primary",
        key_version=3,
    )

    field = vault.encrypt_field("alice@example.com", "email")
    stored = field.model_dump()

    assert stored["salt"]
    assert stored["key_id"] == "pii-primary"
    assert stored["key_version"] == 3
    assert stored["encryption_version"] == CryptoUtils.ENCRYPTION_VERSION
    assert stored["algorithm"] == CryptoUtils.ALGORITHM
    assert stored["kdf"] == CryptoUtils.KDF
    assert stored["kdf_iterations"] == CryptoUtils.KDF_ITERATIONS
    assert "alice@example.com" not in stored.values()
    assert vault.decrypt_field(PIIField(**stored)) == "alice@example.com"


@pytest.mark.asyncio
async def test_pii_encryption_failure_never_stores_plaintext(monkeypatch):
    vault = PIIVault(master_key=CryptoUtils.generate_key())

    def fail_encryption(value):
        raise CryptoError("encryption service unavailable")

    monkeypatch.setattr(vault.crypto, "encrypt", fail_encryption)

    with pytest.raises(CryptoError, match="encryption service unavailable"):
        vault.vault_dict({"email": "alice@example.com"}, ["email"])

    class FactCollection:
        def __init__(self):
            self.inserted = []

        async def count_documents(self, query):
            return 0

        async def insert_one(self, document):
            self.inserted.append(document)

    collection = FactCollection()

    class FactDatabase:
        def __getitem__(self, name):
            assert name == "episodic_memory"
            return collection

    episodic_memory = EpisodicMemory(FactDatabase())
    episodic_memory.pii_vault = vault
    fact = EpisodicFact(
        id="fact-1",
        user_id="user-1",
        conversation_id="conversation-1",
        fact_type="profile",
        fact="alice@example.com",
        confidence=0.9,
        pii_encrypted=True,
        expires_at=datetime.now(timezone.utc) + timedelta(days=90),
    )

    assert await episodic_memory.store_fact(fact) is None
    assert collection.inserted == []


@pytest.mark.asyncio
async def test_pii_fact_context_is_not_persisted_outside_the_encrypted_envelope():
    vault = PIIVault(master_key=CryptoUtils.generate_key())

    class FactCollection:
        def __init__(self):
            self.inserted = []

        async def count_documents(self, query):
            return 0

        async def insert_one(self, document):
            self.inserted.append(document)

    collection = FactCollection()

    class FactDatabase:
        def __getitem__(self, name):
            assert name == "episodic_memory"
            return collection

    episodic_memory = EpisodicMemory(FactDatabase())
    episodic_memory.pii_vault = vault
    fact = EpisodicFact(
        id="fact-2",
        user_id="user-1",
        conversation_id="conversation-1",
        fact_type="profile",
        fact="email: alice@example.com",
        confidence=0.9,
        pii_encrypted=True,
        expires_at=datetime.now(timezone.utc) + timedelta(days=90),
        metadata={"context": "My email is alice@example.com", "source": "entity_extractor"},
    )

    assert await episodic_memory.store_fact(fact) == fact
    persisted = collection.inserted[0]
    assert persisted["metadata"]["context_redacted"] is True
    assert "context" not in persisted["metadata"]
    assert "alice@example.com" not in str(persisted["fact"])
