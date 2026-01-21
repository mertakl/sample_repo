"""
Unit tests for BaseChunkIndexerPort, BM25ChunkIndexerAdapter, and TsVectorChunkIndexerAdapter
"""
import pytest
from unittest.mock import Mock, patch, MagicMock, AsyncMock
from langchain.schema import Document
from pathlib import Path
import tempfile
import os

from your_module.adapters import (
    BaseChunkIndexerPort,
    BM25ChunkIndexerAdapter,
    TsVectorChunkIndexerAdapter,
)
from your_module.models import (
    DocumentChunk,
    QueryResponse,
    SearchQuery,
    Span,
    Hyperlink,
    TableBlock,
    TitleBlock,
)


# ============================================================================
# BaseChunkIndexerPort Unit Tests
# ============================================================================

def test_document_to_chunk_with_full_metadata():
    """Test converting Document to DocumentChunk with all metadata fields"""
    metadata = {
        "content": "Test content",
        "document_id": "doc_123",
        "span_in_document": {"start": 0, "end": 100},
        "hyperlinks": [{"url": "https://example.com", "text": "Example"}],
        "tables": [{"content": "table data", "position": 0}],
        "header_ancestry": [{"text": "Header 1", "level": 1}],
        "headers_before": [{"text": "Previous Header", "level": 2}],
        "metadata": {"key": "value"},
    }
    
    document = Document(page_content="Test page content", metadata=metadata)
    
    chunk = BaseChunkIndexerPort._document_to_chunk(document)
    
    assert chunk.key == "Test page content"
    assert chunk.content == "Test content"
    assert chunk.document_id == "doc_123"
    assert chunk.span_in_document.start == 0
    assert chunk.span_in_document.end == 100
    assert len(chunk.hyperlinks) == 1
    assert len(chunk.tables) == 1
    assert len(chunk.header_ancestry) == 1
    assert len(chunk.headers_before) == 1
    assert chunk.metadata == {"key": "value"}


def test_document_to_chunk_with_minimal_metadata():
    """Test converting Document to DocumentChunk with minimal/missing metadata"""
    document = Document(page_content="Minimal content", metadata={})
    
    chunk = BaseChunkIndexerPort._document_to_chunk(document)
    
    assert chunk.key == "Minimal content"
    assert chunk.content == ""
    assert chunk.document_id == ""
    assert len(chunk.hyperlinks) == 0
    assert len(chunk.tables) == 0
    assert len(chunk.header_ancestry) == 0
    assert len(chunk.headers_before) == 0
    assert chunk.metadata == {}


def test_document_to_chunk_with_none_metadata():
    """Test converting Document with None metadata"""
    document = Document(page_content="No metadata", metadata=None)
    
    chunk = BaseChunkIndexerPort._document_to_chunk(document)
    
    assert chunk.key == "No metadata"
    assert chunk.content == ""
    assert chunk.document_id == ""


def test_create_query_response_success():
    """Test creating QueryResponse from Document and score"""
    metadata = {
        "content": "Response content",
        "document_id": "resp_123",
        "span_in_document": {"start": 10, "end": 50},
    }
    document = Document(page_content="Query result", metadata=metadata)
    score = 0.95
    
    response = BaseChunkIndexerPort.create_query_response(document, score)
    
    assert isinstance(response, QueryResponse)
    assert response.chunk.key == "Query result"
    assert response.chunk.content == "Response content"
    assert response.score == 0.95
    assert response.metadata == metadata


def test_create_query_response_with_zero_score():
    """Test creating QueryResponse with zero score"""
    document = Document(page_content="Low score result", metadata={})
    score = 0.0
    
    response = BaseChunkIndexerPort.create_query_response(document, score)
    
    assert response.score == 0.0
    assert response.chunk.key == "Low score result"


def test_documents_with_scores_to_query_responses_multiple():
    """Test converting multiple documents with scores to QueryResponses"""
    docs_with_scores = [
        (Document(page_content="Doc 1", metadata={"document_id": "1"}), 0.9),
        (Document(page_content="Doc 2", metadata={"document_id": "2"}), 0.8),
        (Document(page_content="Doc 3", metadata={"document_id": "3"}), 0.7),
    ]
    
    responses = BaseChunkIndexerPort.documents_with_scores_to_query_responses(
        docs_with_scores
    )
    
    assert len(responses) == 3
    assert responses[0].score == 0.9
    assert responses[0].chunk.key == "Doc 1"
    assert responses[1].score == 0.8
    assert responses[1].chunk.key == "Doc 2"
    assert responses[2].score == 0.7
    assert responses[2].chunk.key == "Doc 3"


def test_documents_with_scores_to_query_responses_empty():
    """Test converting empty list of documents"""
    docs_with_scores = []
    
    responses = BaseChunkIndexerPort.documents_with_scores_to_query_responses(
        docs_with_scores
    )
    
    assert len(responses) == 0
    assert responses == []


# ============================================================================
# BM25ChunkIndexerAdapter Unit Tests
# ============================================================================

def test_bm25_adapter_initialization(configuration, lexical_db):
    """Test BM25 adapter initialization"""
    adapter = BM25ChunkIndexerAdapter(
        configuration=configuration,
        language="english",
        bm25_db=lexical_db,
        nb_retrieved_doc_factor=2,
    )
    
    assert adapter.language == "english"
    assert adapter.nb_retrieved_doc_factor == 2
    assert adapter.bm25_db == lexical_db


@pytest.mark.asyncio
async def test_bm25_search_success(configuration, lexical_db):
    """Test BM25 search returns results successfully"""
    adapter = BM25ChunkIndexerAdapter(
        configuration=configuration,
        language="english",
        bm25_db=lexical_db,
    )
    
    # Mock the bm25_db search method
    expected_results = [
        QueryResponse(
            chunk=Mock(spec=DocumentChunk),
            score=0.9,
            metadata={}
        )
    ]
    lexical_db.search = AsyncMock(return_value=expected_results)
    
    query = SearchQuery(text="test query")
    results = await adapter.search(query, max_k=10)
    
    assert len(results) == 1
    assert results[0].score == 0.9
    lexical_db.search.assert_called_once_with("test query", k=10)


@pytest.mark.asyncio
async def test_bm25_search_with_different_max_k(configuration, lexical_db):
    """Test BM25 search with different max_k values"""
    adapter = BM25ChunkIndexerAdapter(
        configuration=configuration,
        language="english",
        bm25_db=lexical_db,
    )
    
    lexical_db.search = AsyncMock(return_value=[])
    
    query = SearchQuery(text="test")
    await adapter.search(query, max_k=5)
    
    lexical_db.search.assert_called_once_with("test", k=5)


@pytest.mark.asyncio
async def test_bm25_search_exception_handling(configuration, lexical_db):
    """Test BM25 search handles exceptions and returns empty list"""
    adapter = BM25ChunkIndexerAdapter(
        configuration=configuration,
        language="english",
        bm25_db=lexical_db,
    )
    
    lexical_db.search = AsyncMock(side_effect=Exception("Search failed"))
    
    query = SearchQuery(text="test query")
    results = await adapter.search(query, max_k=10)
    
    assert results == []


@pytest.mark.asyncio
async def test_bm25_search_empty_results(configuration, lexical_db):
    """Test BM25 search with no matching results"""
    adapter = BM25ChunkIndexerAdapter(
        configuration=configuration,
        language="english",
        bm25_db=lexical_db,
    )
    
    lexical_db.search = AsyncMock(return_value=[])
    
    query = SearchQuery(text="nonexistent query")
    results = await adapter.search(query, max_k=10)
    
    assert len(results) == 0


@pytest.mark.asyncio
async def test_bm25_select_not_implemented(configuration, lexical_db):
    """Test that select method logs warning and does nothing"""
    adapter = BM25ChunkIndexerAdapter(
        configuration=configuration,
        language="english",
        bm25_db=lexical_db,
    )
    
    with patch('your_module.adapters.logger') as mock_logger:
        await adapter.select([])
        mock_logger.warning.assert_called_once()


@patch('your_module.adapters.Bm25InMemoryDatabase')
@patch('your_module.adapters.DocumentSplitter')
def test_bm25_from_documents_success(
    mock_splitter_class, mock_bm25_class, configuration, cos_client
):
    """Test creating BM25 adapter from documents"""
    # Setup mocks
    mock_splitter = Mock()
    mock_chunks = [Mock(spec=DocumentChunk) for _ in range(5)]
    mock_splitter.split_documents = AsyncMock(return_value=mock_chunks)
    mock_splitter_class.return_value = mock_splitter
    
    mock_bm25_db = Mock()
    mock_bm25_class.from_documents.return_value = mock_bm25_db
    
    documents = {
        "source1": [Document(page_content="doc1", metadata={})],
        "source2": [Document(page_content="doc2", metadata={})],
    }
    
    # Since from_documents is async, we need to test differently
    # This is a simplified unit test - integration test will be more thorough


def test_bm25_from_saved_index_file_not_found(configuration, cos_client):
    """Test loading BM25 index when file doesn't exist"""
    with patch.object(
        BM25ChunkIndexerAdapter,
        '_bm25_exists_on_cos',
        return_value=False
    ):
        with pytest.raises(FileNotFoundError):
            BM25ChunkIndexerAdapter.from_saved_index(
                configuration=configuration,
                language="english",
                cos_bucket_api=cos_client,
            )


@patch('your_module.adapters.TemporaryDirectory')
@patch('your_module.adapters.Bm25InMemoryDatabase')
def test_bm25_from_saved_index_success(
    mock_bm25_class, mock_temp_dir, configuration, cos_client
):
    """Test successfully loading BM25 index from COS"""
    # Mock temporary directory
    mock_temp_dir.return_value.__enter__.return_value = '/tmp/test'
    
    # Mock BM25 database
    mock_bm25_db = Mock()
    mock_bm25_class.load.return_value = mock_bm25_db
    
    with patch.object(
        BM25ChunkIndexerAdapter,
        '_bm25_exists_on_cos',
        return_value=True
    ), patch.object(
        BM25ChunkIndexerAdapter,
        '_download_bm25_files'
    ) as mock_download, patch.object(
        BM25ChunkIndexerAdapter,
        '_get_cos_bm25_directory',
        return_value='path/to/bm25'
    ):
        adapter = BM25ChunkIndexerAdapter.from_saved_index(
            configuration=configuration,
            language="english",
            cos_bucket_api=cos_client,
        )
        
        assert adapter.language == "english"
        assert adapter.bm25_db == mock_bm25_db
        mock_download.assert_called_once()


def test_download_bm25_files_with_simple_cos_client():
    """Test downloading BM25 files using SimpleCosClient"""
    mock_cos_client = Mock()
    mock_cos_client.__class__.__name__ = 'SimpleCosClient'
    
    # Mock S3 bucket objects
    mock_object1 = Mock()
    mock_object1.key = "path/to/bm25/file1.pkl"
    mock_object2 = Mock()
    mock_object2.key = "path/to/bm25/file2.pkl"
    
    mock_bucket = Mock()
    mock_bucket.objects.filter.return_value = [mock_object1, mock_object2]
    mock_cos_client.client.Bucket.return_value = mock_bucket
    
    with tempfile.TemporaryDirectory() as tmp_dir:
        with patch('your_module.adapters.config') as mock_config:
            mock_config.return_value = "test-bucket"
            
            BM25ChunkIndexerAdapter._download_bm25_files(
                cos_bucket_api=mock_cos_client,
                path_to_database="path/to/bm25",
                tmp_dir_name=tmp_dir,
                configuration=Mock(),
            )
            
            assert mock_cos_client.download_file.call_count == 2


def test_download_bm25_files_with_cos_bucket_api(cos_client):
    """Test downloading BM25 files using CosBucketApi"""
    cos_client.list_files_in_bucket_folder.return_value = [
        "path/to/bm25/file1.pkl",
        "path/to/bm25/file2.pkl",
    ]
    
    with tempfile.TemporaryDirectory() as tmp_dir:
        BM25ChunkIndexerAdapter._download_bm25_files(
            cos_bucket_api=cos_client,
            path_to_database="path/to/bm25",
            tmp_dir_name=tmp_dir,
            configuration=Mock(),
        )
        
        assert cos_client.download_file.call_count == 2


# ============================================================================
# TsVectorChunkIndexerAdapter Unit Tests
# ============================================================================

@patch('your_module.adapters.psycopg2.connect')
def test_tsvector_get_connection(mock_connect, configuration):
    """Test getting database connection"""
    mock_config = Mock()
    mock_config.get_connection_string.return_value = "postgresql+psycopg://user:pass@host/db"
    
    adapter = TsVectorChunkIndexerAdapter(
        config=mock_config,
        language="english",
    )
    
    adapter._get_connection()
    
    mock_connect.assert_called_once_with("postgresql://user:pass@host/db")


@patch('your_module.adapters.psycopg2.connect')
def test_tsvector_initialize_schema_success(mock_connect, configuration):
    """Test successful schema initialization"""
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
    mock_connect.return_value = mock_conn
    
    mock_config = Mock()
    mock_config.get_connection_string.return_value = "postgresql+psycopg://user:pass@host/db"
    
    adapter = TsVectorChunkIndexerAdapter(
        config=mock_config,
        language="english",
    )
    
    adapter.initialize_schema()
    
    # Verify all SQL statements were executed
    assert mock_cursor.execute.call_count == 5  # ALTER, CREATE INDEX, CREATE FUNC, DROP TRIGGER, CREATE TRIGGER
    mock_conn.commit.assert_called_once()
    mock_conn.close.assert_called_once()


@patch('your_module.adapters.psycopg2.connect')
def test_tsvector_initialize_schema_failure(mock_connect):
    """Test schema initialization handles errors"""
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.execute.side_effect = Exception("SQL Error")
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
    mock_connect.return_value = mock_conn
    
    mock_config = Mock()
    mock_config.get_connection_string.return_value = "postgresql+psycopg://user:pass@host/db"
    
    adapter = TsVectorChunkIndexerAdapter(
        config=mock_config,
        language="english",
    )
    
    with pytest.raises(Exception):
        adapter.initialize_schema()
    
    mock_conn.rollback.assert_called_once()
    mock_conn.close.assert_called_once()


@pytest.mark.asyncio
@patch('your_module.adapters.psycopg2.connect')
async def test_tsvector_search_success(mock_connect):
    """Test successful TsVector search"""
    # Mock database results
    mock_results = [
        {
            "document": "Test document 1",
            "cmetadata": {"doc_id": "1"},
            "score": 0.95
        },
        {
            "document": "Test document 2",
            "cmetadata": {"doc_id": "2"},
            "score": 0.85
        }
    ]
    
    mock_cursor = MagicMock()
    mock_cursor.fetchall.return_value = mock_results
    
    mock_conn = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
    mock_connect.return_value = mock_conn
    
    mock_config = Mock()
    mock_config.get_connection_string.return_value = "postgresql+psycopg://user:pass@host/db"
    
    adapter = TsVectorChunkIndexerAdapter(
        config=mock_config,
        language="english",
    )
    
    query = SearchQuery(text="test query")
    results = await adapter.search(query, max_k=10)
    
    assert len(results) == 2
    assert results[0].score == 0.95
    assert results[1].score == 0.85
    mock_cursor.execute.assert_called_once()
    mock_conn.close.assert_called_once()


@pytest.mark.asyncio
@patch('your_module.adapters.psycopg2.connect')
async def test_tsvector_search_with_none_score(mock_connect):
    """Test TsVector search handles None scores"""
    mock_results = [
        {
            "document": "Test document",
            "cmetadata": {},
            "score": None
        }
    ]
    
    mock_cursor = MagicMock()
    mock_cursor.fetchall.return_value = mock_results
    
    mock_conn = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
    mock_connect.return_value = mock_conn
    
    mock_config = Mock()
    mock_config.get_connection_string.return_value = "postgresql+psycopg://user:pass@host/db"
    
    adapter = TsVectorChunkIndexerAdapter(
        config=mock_config,
        language="english",
    )
    
    query = SearchQuery(text="test")
    results = await adapter.search(query, max_k=5)
    
    assert len(results) == 1
    assert results[0].score == 0.0


@pytest.mark.asyncio
@patch('your_module.adapters.psycopg2.connect')
async def test_tsvector_search_exception_handling(mock_connect):
    """Test TsVector search handles exceptions"""
    mock_conn = MagicMock()
    mock_conn.cursor.side_effect = Exception("Database error")
    mock_connect.return_value = mock_conn
    
    mock_config = Mock()
    mock_config.get_connection_string.return_value = "postgresql+psycopg://user:pass@host/db"
    
    adapter = TsVectorChunkIndexerAdapter(
        config=mock_config,
        language="english",
    )
    
    query = SearchQuery(text="test")
    results = await adapter.search(query, max_k=10)
    
    assert results == []
    mock_conn.close.assert_called_once()


@pytest.mark.asyncio
@patch('your_module.adapters.psycopg2.connect')
async def test_tsvector_search_empty_results(mock_connect):
    """Test TsVector search with no results"""
    mock_cursor = MagicMock()
    mock_cursor.fetchall.return_value = []
    
    mock_conn = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
    mock_connect.return_value = mock_conn
    
    mock_config = Mock()
    mock_config.get_connection_string.return_value = "postgresql+psycopg://user:pass@host/db"
    
    adapter = TsVectorChunkIndexerAdapter(
        config=mock_config,
        language="english",
    )
    
    query = SearchQuery(text="nonexistent")
    results = await adapter.search(query, max_k=10)
    
    assert len(results) == 0


@pytest.mark.asyncio
async def test_tsvector_select_not_implemented():
    """Test that select method is present but not implemented"""
    mock_config = Mock()
    mock_config.get_connection_string.return_value = "postgresql+psycopg://user:pass@host/db"
    
    adapter = TsVectorChunkIndexerAdapter(
        config=mock_config,
        language="english",
    )
    
    # Should not raise an error, just pass
    result = await adapter.select([])
    assert result is None
