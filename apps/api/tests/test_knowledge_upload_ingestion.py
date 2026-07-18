import types

import pytest
from fastapi import BackgroundTasks, HTTPException

from app.api.v1.endpoints.knowledge import _hydrate_product_cards, _product_card_from_data, upload_document
from app.config import Settings
from app.services.knowledge_service import KnowledgeService


@pytest.fixture
def knowledge_service():
    return KnowledgeService(Settings(VECTOR_BACKEND="atlas"))


@pytest.mark.asyncio
async def test_detect_source_type_uses_mime_or_extension(knowledge_service):
    assert knowledge_service.detect_source_type("application/pdf", "ignored.bin") == "pdf"
    assert knowledge_service.detect_source_type("application/octet-stream", "manual.DOCX") == "docx"
    assert knowledge_service.detect_source_type("text/plain; charset=utf-8", "notes.txt") == "txt"
    assert knowledge_service.detect_source_type("", "catalog.csv") == "csv"
    assert knowledge_service.detect_source_type("application/octet-stream", "archive.zip") is None


@pytest.mark.asyncio
async def test_products_by_skus_hydrates_variant_siblings_for_card_payload():
    class FakeCursor:
        def __init__(self, rows):
            self.rows = rows
            self.index = 0

        def __aiter__(self):
            self.index = 0
            return self

        async def __anext__(self):
            if self.index >= len(self.rows):
                raise StopAsyncIteration
            row = self.rows[self.index]
            self.index += 1
            return row

    class FakeCollection:
        def __init__(self, rows):
            self.rows = rows
            self.queries = []

        def find(self, query):
            self.queries.append(query)
            group_id = query.get("product_data.product_group_id")
            rows = [
                row
                for row in self.rows
                if row.get("content_type") == query.get("content_type")
                and row.get("product_data", {}).get("product_group_id") == group_id
            ]
            return FakeCursor(rows)

    rows = [
        {
            "content_type": "product",
            "product_data": {
                "sku": "DENON-BLK",
                "name": "Denon Home 150 - Black",
                "parent_name": "Denon Home 150",
                "product_group_id": "shopify:denon-home-150",
                "variant_id": "black",
                "variant_sku": "DENON-BLK",
                "variant_options": {"Colour": "Black"},
                "price": 4190000,
                "currency": "INR",
                "product_url": "https://example.com/products/denon-home-150",
                "variant_url": "https://example.com/products/denon-home-150?variant=black",
            },
        },
        {
            "content_type": "product",
            "product_data": {
                "sku": "DENON-WHT",
                "name": "Denon Home 150 - White",
                "parent_name": "Denon Home 150",
                "product_group_id": "shopify:denon-home-150",
                "variant_id": "white",
                "variant_sku": "DENON-WHT",
                "variant_options": {"Colour": "White"},
                "price": 4290000,
                "currency": "INR",
                "product_url": "https://example.com/products/denon-home-150",
                "variant_url": "https://example.com/products/denon-home-150?variant=white",
            },
        },
    ]
    collection = FakeCollection(rows)
    selected_product = _product_card_from_data(rows[0]["product_data"])

    products = await _hydrate_product_cards(collection, [selected_product])

    assert len(products) == 1
    assert products[0]["name"] == "Denon Home 150"
    assert products[0]["variant_count"] == 2
    assert [variant["variant_sku"] for variant in products[0]["variants"]] == ["DENON-BLK", "DENON-WHT"]
    assert products[0]["variants"][0]["is_default"] is True


@pytest.mark.asyncio
async def test_extract_csv_text_labels_rows_for_search(knowledge_service):
    text = await knowledge_service._extract_text(
        b"sku,name,price\nFAU-001,Chrome Faucet,3499\nSHW-002,Rain Shower,12999\n",
        "application/octet-stream",
        "catalog.csv",
    )

    assert "Row 1" in text
    assert "sku: FAU-001" in text
    assert "name: Chrome Faucet" in text
    assert "price: 12999" in text


@pytest.mark.asyncio
async def test_extract_headerless_csv_keeps_first_row(knowledge_service):
    text = await knowledge_service._extract_text(
        b"FAU-001,Chrome Faucet,3499\n",
        "text/csv",
        "catalog.csv",
    )

    assert "Row 1: FAU-001, Chrome Faucet, 3499" in text


@pytest.mark.asyncio
async def test_extract_pdf_text_with_pypdf(monkeypatch, knowledge_service):
    class FakePage:
        def __init__(self, text):
            self.text = text

        def extract_text(self):
            return self.text

    class FakePdfReader:
        def __init__(self, stream):
            self.pages = [FakePage("First page"), FakePage("Second page")]

    monkeypatch.setitem(
        __import__("sys").modules,
        "pypdf",
        types.SimpleNamespace(PdfReader=FakePdfReader),
    )

    text = await knowledge_service._extract_text(b"%PDF fake", "application/pdf", "guide.pdf")

    assert "Page 1\nFirst page" in text
    assert "Page 2\nSecond page" in text


@pytest.mark.asyncio
async def test_extract_docx_text_with_python_docx(monkeypatch, knowledge_service):
    class Paragraph:
        def __init__(self, text):
            self.text = text

    class Cell:
        def __init__(self, text):
            self.text = text

    class Row:
        cells = [Cell("Feature"), Cell("Value")]

    class Table:
        rows = [Row()]

    class FakeDocument:
        paragraphs = [Paragraph("Intro"), Paragraph("Details")]
        tables = [Table()]

    monkeypatch.setitem(
        __import__("sys").modules,
        "docx",
        types.SimpleNamespace(Document=lambda stream: FakeDocument()),
    )

    text = await knowledge_service._extract_text(
        b"fake docx",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "guide.docx",
    )

    assert "Intro" in text
    assert "Details" in text
    assert "Feature | Value" in text


class FakeUploadFile:
    filename = "catalog.csv"
    content_type = "application/octet-stream"

    async def read(self):
        return b"sku,name\nFAU-001,Chrome Faucet\n"


class FakeEndpointKnowledgeService:
    def __init__(self):
        self.started = None
        self.processed = None

    def detect_source_type(self, content_type, filename):
        return KnowledgeService(Settings()).detect_source_type(content_type, filename)

    async def start_document_upload(self, **kwargs):
        self.started = kwargs
        return "job-123"

    async def process_document_upload(self, **kwargs):
        self.processed = kwargs


@pytest.mark.asyncio
async def test_upload_endpoint_accepts_supported_extension_when_mime_is_generic():
    service = FakeEndpointKnowledgeService()

    response = await upload_document(
        background_tasks=BackgroundTasks(),
        file=FakeUploadFile(),
        content_type="guide",
        brand_id="brand-1",
        agent_id="agent-1",
        product_data=None,
        dealer_data=None,
        knowledge_service=service,
        current_user=None,
    )

    assert response.job_id == "job-123"
    assert service.started["filename"] == "catalog.csv"
    assert service.started["content_type_header"] == "application/octet-stream"
    assert service.started["agent_id"] == "agent-1"


@pytest.mark.asyncio
async def test_upload_endpoint_rejects_unknown_source_type():
    service = FakeEndpointKnowledgeService()
    file = FakeUploadFile()
    file.filename = "malware.exe"

    with pytest.raises(HTTPException) as exc_info:
        await upload_document(
            background_tasks=BackgroundTasks(),
            file=file,
            content_type="guide",
            brand_id="brand-1",
            product_data=None,
            dealer_data=None,
            knowledge_service=service,
            current_user=None,
        )

    assert exc_info.value.status_code == 400
    assert "Allowed: PDF, DOCX, TXT, MD, HTML, JSON, CSV" in exc_info.value.detail


class FakeCollection:
    def __init__(self):
        self.inserted = []

    async def insert_one(self, document):
        self.inserted.append(document)


class MetadataKnowledgeService(KnowledgeService):
    def __init__(self):
        super().__init__(Settings(VECTOR_BACKEND="atlas"))
        self.collection = FakeCollection()

    async def _ensure_connection(self, brand_id=None):
        return None

    async def _resolve_brand_scope(self, identifier):
        return {
            "brand_id": "brand-uuid",
            "brand_slug": "brand-slug",
            "aliases": [identifier, "brand-uuid", "brand-slug"],
        }

    async def _generate_embeddings(self, texts):
        return [[0.1, 0.2] for _ in texts]


@pytest.mark.asyncio
async def test_process_document_upload_stores_source_metadata():
    service = MetadataKnowledgeService()
    await service.job_store.set("job-123", {"status": "pending"})

    await service.process_document_upload(
        job_id="job-123",
        content=b"First paragraph.\n\nSecond paragraph.",
        filename="guide.md",
        content_type_header="text/markdown",
        kb_content_type="guide",
        brand_id="brand-input",
        agent_id="agent-1",
        folder_path="/policies/refunds",
    )

    assert len(service.collection.inserted) == 1
    metadata = service.collection.inserted[0]["metadata"]
    assert metadata["brand_id"] == "brand-uuid"
    assert metadata["brand_slug"] == "brand-slug"
    assert metadata["agent_id"] == "agent-1"
    assert metadata["filename"] == "guide.md"
    assert metadata["content_type_header"] == "text/markdown"
    assert metadata["source_type"] == "md"
    assert metadata["job_id"] == "job-123"
    assert metadata["folder"] == "/policies/refunds"
    assert metadata["path"] == "/policies/refunds/guide.md"
