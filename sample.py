import pytest
from langchain.schema import Document

from your_module import BaseChunkIndexerPort
from your_models import DocumentChunk, QueryResponse


def test_document_to_chunk_success():
    doc = Document(
        page_content="hello world",
        metadata={
            "content": "content",
            "document_id": "doc-1",
            "span_in_document": {"start": 0, "end": 10},
            "hyperlinks": [],
            "tables": [],
            "header_ancestry": [],
            "headers_before": [],
            "metadata": {"source": "unit-test"},
        },
    )

    chunk = BaseChunkIndexerPort._document_to_chunk(doc)

    assert isinstance(chunk, DocumentChunk)
    assert chunk.key == "hello world"
    assert chunk.document_id == "doc-1"
    assert chunk.metadata["source"] == "unit-test"


def test_document_to_chunk_with_missing_metadata():
    doc = Document(page_content="hello", metadata=None)

    chunk = BaseChunkIndexerPort._document_to_chunk(doc)

    assert chunk.key == "hello"
    assert chunk.document_id == ""
    assert chunk.metadata == {}


def test_create_query_response_success():
    doc = Document(page_content="abc", metadata={"document_id": "x"})
    score = 0.42

    response = BaseChunkIndexerPort.create_query_response(doc, score)

    assert isinstance(response, QueryResponse)
    assert response.score == score
    assert response.chunk.key == "abc"


def test_document_to_chunk_invalid_nested_model_raises():
    doc = Document(
        page_content="abc",
        metadata={"span_in_document": "INVALID"},
    )

    with pytest.raises(Exception):
        BaseChunkIndexerPort._document_to_chunk(doc)
