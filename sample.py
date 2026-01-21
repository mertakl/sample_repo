"""
Integration tests for BM25ChunkIndexerAdapter and TsVectorChunkIndexerAdapter.
Tests cover both success and failure scenarios.
Fixed to properly handle Pydantic model validation.
"""

import pytest
import asyncio
from unittest.mock import Mock, patch, MagicMock, AsyncMock
from pathlib import Path
from tempfile import TemporaryDirectory
import psycopg2
from psycopg2.extras import RealDictCursor
from typing import List

# Assuming these imports based on your code structure
from your_module.adapters import BM25ChunkIndexerAdapter, TsVectorChunkIndexerAdapter
from your_module.models import (
    Document, DocumentChunk, SearchQuery, QueryResponse,
    Configuration, Span, Hyperlink, TableBlock, TitleBlock,
    ChunkFilterClause
)
from your_module.database import Bm25InMemoryDatabase, PGVectorDBConfig


# ============================================================================
# FIXTURES
# ============================================================================

@pytest.fixture
def sample_configuration():
    """Create a sample configuration object."""
    # Create actual Configuration object instead of Mock
    config = Configuration(
        cos_version="v1.0",
        document_splitter={},  # Provide actual config structure
        document_parser={
            "document_object_cos_folder": "test_folder",
            "sources": {"source1": {}, "source2": {}}
        }
    )
    return config


@pytest.fixture
def sample_documents():
    """Create sample Document objects for testing."""
    return [
        Document(
            page_content="Test content 1",
            metadata={
                "content": "Full content 1",
                "document_id": "doc1",
                "span_in_document": {"start": 0, "end": 100},
                "hyperlinks": [],
                "tables": [],
                "header_ancestry": [],
                "headers_before": [],
                "metadata": {"key": "value1"}
            }
        ),
        Document(
            page_content="Test content 2",
            metadata={
                "content": "Full content 2",
                "document_id": "doc2",
                "span_in_document": {"start": 0, "end": 150},
                "hyperlinks": [],
                "tables": [],
                "header_ancestry": [],
                "headers_before": [],
                "metadata": {"key": "value2"}
            }
        )
    ]


@pytest.fixture
def sample_chunks():
    """Create sample DocumentChunk objects."""
    return [
        DocumentChunk(
            key="chunk1",
            content="Content chunk 1",
            document_id="doc1",
            span_in_document=Span(start=0, end=50),
            hyperlinks=[],
            tables=[],
            header_ancestry=[],
            headers_before=[],
            metadata={}
        ),
        DocumentChunk(
            key="chunk2",
            content="Content chunk 2",
            document_id="doc2",
            span_in_document=Span(start=0, end=60),
            hyperlinks=[],
            tables=[],
            header_ancestry=[],
            headers_before=[],
            metadata={}
        )
    ]


@pytest.fixture
def sample_query_responses(sample_chunks):
    """Create sample QueryResponse objects."""
    return [
        QueryResponse(
            chunk=sample_chunks[0],
            score=0.95,
            metadata={"doc_id": "doc1"}
        ),
        QueryResponse(
            chunk=sample_chunks[1],
            score=0.85,
            metadata={"doc_id": "doc2"}
        )
    ]


@pytest.fixture
def mock_cos_bucket_api():
    """Create a mock COS bucket API."""
    mock_api = Mock()
    mock_api.download_file = Mock()
    mock_api.list_files_in_bucket_folder = Mock(return_value=[
        "path/to/file1.pkl",
        "path/to/file2.pkl"
    ])
    return mock_api


@pytest.fixture
def mock_bm25_db(sample_query_responses):
    """Create a mock BM25 in-memory database."""
    mock_db = Mock(spec=Bm25InMemoryDatabase)
    
    # Use the actual QueryResponse objects
    async def mock_search(query, k):
        return sample_query_responses[:k]
    
    mock_db.search = AsyncMock(side_effect=mock_search)
    return mock_db


@pytest.fixture
def postgres_config():
    """Create a PostgreSQL configuration for testing."""
    # Create actual config or use Mock properly
    config = Mock(spec=PGVectorDBConfig)
    config.get_connection_string = Mock(
        return_value="postgresql://user:pass@localhost:5432/testdb"
    )
    return config


# ============================================================================
# BM25ChunkIndexerAdapter TESTS
# ============================================================================

class TestBM25ChunkIndexerAdapter:
    """Test suite for BM25ChunkIndexerAdapter."""

    @pytest.mark.asyncio
    async def test_from_documents_success(
        self, sample_configuration, mock_cos_bucket_api, sample_chunks, sample_documents
    ):
        """Test successful creation of BM25 adapter from documents."""
        data_source_to_documents = {
            "source1": sample_documents
        }

        with patch('your_module.adapters.DocumentSplitter') as mock_splitter_class, \
             patch('your_module.adapters.Bm25InMemoryDatabase') as mock_bm25_class, \
             patch('your_module.adapters.v_cos_patch', return_value="v1_0"), \
             patch('your_module.adapters.logger'):
            
            # Setup mocks
            mock_splitter_instance = Mock()
            mock_splitter_instance.split_documents = AsyncMock(return_value=sample_chunks)
            mock_splitter_class.return_value = mock_splitter_instance
            
            mock_bm25_instance = Mock(spec=Bm25InMemoryDatabase)
            mock_bm25_class.from_documents = Mock(return_value=mock_bm25_instance)
            
            # Execute
            adapter = await BM25ChunkIndexerAdapter.from_documents(
                configuration=sample_configuration,
                language="english",
                cos_bucket_api=mock_cos_bucket_api,
                data_source_to_documents=data_source_to_documents,
                nb_retrieved_doc_factor=2
            )
            
            # Assertions
            assert adapter is not None
            assert adapter.language == "english"
            assert adapter.nb_retrieved_doc_factor == 2
            assert adapter.bm25_db == mock_bm25_instance
            mock_splitter_instance.split_documents.assert_called_once()
            mock_bm25_class.from_documents.assert_called_once_with(
                sample_chunks,
                nb_retrieved_doc_factor=2
            )

    @pytest.mark.asyncio
    async def test_from_documents_with_empty_documents(
        self, sample_configuration, mock_cos_bucket_api
    ):
        """Test creation with empty document list."""
        data_source_to_documents = {"source1": []}

        with patch('your_module.adapters.DocumentSplitter') as mock_splitter_class, \
             patch('your_module.adapters.Bm25InMemoryDatabase') as mock_bm25_class, \
             patch('your_module.adapters.v_cos_patch', return_value="v1_0"), \
             patch('your_module.adapters.logger'):
            
            mock_splitter_instance = Mock()
            mock_splitter_instance.split_documents = AsyncMock(return_value=[])
            mock_splitter_class.return_value = mock_splitter_instance
            
            mock_bm25_instance = Mock(spec=Bm25InMemoryDatabase)
            mock_bm25_class.from_documents = Mock(return_value=mock_bm25_instance)
            
            adapter = await BM25ChunkIndexerAdapter.from_documents(
                configuration=sample_configuration,
                language="english",
                cos_bucket_api=mock_cos_bucket_api,
                data_source_to_documents=data_source_to_documents
            )
            
            assert adapter is not None
            mock_bm25_class.from_documents.assert_called_once_with(
                [], nb_retrieved_doc_factor=1
            )

    @pytest.mark.asyncio
    async def test_from_documents_failure_splitting_error(
        self, sample_configuration, mock_cos_bucket_api, sample_documents
    ):
        """Test failure when document splitting raises an error."""
        data_source_to_documents = {"source1": sample_documents}

        with patch('your_module.adapters.DocumentSplitter') as mock_splitter_class, \
             patch('your_module.adapters.v_cos_patch', return_value="v1_0"), \
             patch('your_module.adapters.logger'):
            
            mock_splitter_instance = Mock()
            mock_splitter_instance.split_documents = AsyncMock(
                side_effect=Exception("Splitting failed")
            )
            mock_splitter_class.return_value = mock_splitter_instance
            
            with pytest.raises(Exception, match="Splitting failed"):
                await BM25ChunkIndexerAdapter.from_documents(
                    configuration=sample_configuration,
                    language="english",
                    cos_bucket_api=mock_cos_bucket_api,
                    data_source_to_documents=data_source_to_documents
                )

    def test_from_saved_index_success(
        self, sample_configuration, mock_cos_bucket_api, mock_bm25_db
    ):
        """Test successful loading of saved BM25 index from COS."""
        with patch.object(
            BM25ChunkIndexerAdapter, '_v_cos_patch', return_value="v1_0"
        ), patch.object(
            BM25ChunkIndexerAdapter, '_get_cos_bm25_directory', 
            return_value="path/to/bm25"
        ), patch.object(
            BM25ChunkIndexerAdapter, '_bm25_exists_on_cos', return_value=True
        ), patch.object(
            BM25ChunkIndexerAdapter, '_download_bm25_files'
        ), patch(
            'your_module.adapters.Bm25InMemoryDatabase.load',
            return_value=mock_bm25_db
        ), patch('your_module.adapters.TemporaryDirectory') as mock_tempdir, \
           patch('your_module.adapters.logger'):
            
            # Mock TemporaryDirectory context manager
            mock_tempdir.return_value.__enter__ = Mock(return_value="/tmp/test")
            mock_tempdir.return_value.__exit__ = Mock(return_value=False)
            
            adapter = BM25ChunkIndexerAdapter.from_saved_index(
                configuration=sample_configuration,
                language="english",
                cos_bucket_api=mock_cos_bucket_api
            )
            
            assert adapter is not None
            assert adapter.language == "english"
            assert adapter.bm25_db == mock_bm25_db

    def test_from_saved_index_failure_not_found(
        self, sample_configuration, mock_cos_bucket_api
    ):
        """Test failure when BM25 index doesn't exist on COS."""
        with patch.object(
            BM25ChunkIndexerAdapter, '_v_cos_patch', return_value="v1_0"
        ), patch.object(
            BM25ChunkIndexerAdapter, '_get_cos_bm25_directory',
            return_value="path/to/bm25"
        ), patch.object(
            BM25ChunkIndexerAdapter, '_bm25_exists_on_cos', return_value=False
        ):
            
            with pytest.raises(FileNotFoundError, match="is not a valid BM25 backup"):
                BM25ChunkIndexerAdapter.from_saved_index(
                    configuration=sample_configuration,
                    language="english",
                    cos_bucket_api=mock_cos_bucket_api
                )

    def test_from_saved_index_failure_loading_error(
        self, sample_configuration, mock_cos_bucket_api
    ):
        """Test failure during BM25 index loading."""
        with patch.object(
            BM25ChunkIndexerAdapter, '_v_cos_patch', return_value="v1_0"
        ), patch.object(
            BM25ChunkIndexerAdapter, '_get_cos_bm25_directory',
            return_value="path/to/bm25"
        ), patch.object(
            BM25ChunkIndexerAdapter, '_bm25_exists_on_cos', return_value=True
        ), patch.object(
            BM25ChunkIndexerAdapter, '_download_bm25_files'
        ), patch(
            'your_module.adapters.Bm25InMemoryDatabase.load',
            side_effect=Exception("Loading failed")
        ), patch('your_module.adapters.TemporaryDirectory') as mock_tempdir, \
           patch('your_module.adapters.logger'):
            
            mock_tempdir.return_value.__enter__ = Mock(return_value="/tmp/test")
            mock_tempdir.return_value.__exit__ = Mock(return_value=False)
            
            with pytest.raises(Exception, match="Loading failed"):
                BM25ChunkIndexerAdapter.from_saved_index(
                    configuration=sample_configuration,
                    language="english",
                    cos_bucket_api=mock_cos_bucket_api
                )

    @pytest.mark.asyncio
    async def test_search_success(self, sample_configuration, mock_bm25_db):
        """Test successful BM25 search operation."""
        adapter = BM25ChunkIndexerAdapter(
            configuration=sample_configuration,
            language="english",
            bm25_db=mock_bm25_db
        )
        
        query = SearchQuery(text="test query")
        results = await adapter.search(query, max_k=5)
        
        assert len(results) == 2
        assert isinstance(results[0], QueryResponse)
        assert results[0].score == 0.95
        assert results[1].score == 0.85
        mock_bm25_db.search.assert_called_once_with("test query", k=5)

    @pytest.mark.asyncio
    async def test_search_with_default_max_k(self, sample_configuration, mock_bm25_db):
        """Test search with default max_k parameter."""
        adapter = BM25ChunkIndexerAdapter(
            configuration=sample_configuration,
            language="english",
            bm25_db=mock_bm25_db
        )
        
        query = SearchQuery(text="test query")
        results = await adapter.search(query)
        
        assert len(results) == 2
        mock_bm25_db.search.assert_called_once_with("test query", k=10)

    @pytest.mark.asyncio
    async def test_search_failure_exception(self, sample_configuration):
        """Test search failure when exception occurs."""
        mock_bm25_db = Mock(spec=Bm25InMemoryDatabase)
        mock_bm25_db.search = AsyncMock(side_effect=Exception("Search failed"))
        
        with patch('your_module.adapters.logger'):
            adapter = BM25ChunkIndexerAdapter(
                configuration=sample_configuration,
                language="english",
                bm25_db=mock_bm25_db
            )
            
            query = SearchQuery(text="test query")
            results = await adapter.search(query, max_k=5)
            
            assert results == []

    @pytest.mark.asyncio
    async def test_search_returns_empty_list(self, sample_configuration):
        """Test search when no results are found."""
        mock_bm25_db = Mock(spec=Bm25InMemoryDatabase)
        mock_bm25_db.search = AsyncMock(return_value=[])
        
        adapter = BM25ChunkIndexerAdapter(
            configuration=sample_configuration,
            language="english",
            bm25_db=mock_bm25_db
        )
        
        query = SearchQuery(text="nonexistent query")
        results = await adapter.search(query, max_k=10)
        
        assert results == []
        mock_bm25_db.search.assert_called_once()

    @pytest.mark.asyncio
    async def test_select_not_implemented(self, sample_configuration, mock_bm25_db):
        """Test that select operation logs warning."""
        adapter = BM25ChunkIndexerAdapter(
            configuration=sample_configuration,
            language="english",
            bm25_db=mock_bm25_db
        )
        
        with patch('your_module.adapters.logger') as mock_logger:
            filter_clauses = []
            await adapter.select(filter_clauses)
            
            # Verify warning was logged
            mock_logger.warning.assert_called_once()


# ============================================================================
# TsVectorChunkIndexerAdapter TESTS
# ============================================================================

class TestTsVectorChunkIndexerAdapter:
    """Test suite for TsVectorChunkIndexerAdapter."""

    def test_initialize_schema_success(self, postgres_config):
        """Test successful schema initialization."""
        mock_conn = Mock()
        mock_cursor = Mock()
        mock_conn.cursor = Mock(return_value=mock_cursor)
        mock_cursor.__enter__ = Mock(return_value=mock_cursor)
        mock_cursor.__exit__ = Mock(return_value=False)
        mock_conn.commit = Mock()
        mock_conn.close = Mock()
        
        adapter = TsVectorChunkIndexerAdapter(
            config=postgres_config,
            language="english"
        )
        
        with patch.object(adapter, '_get_connection', return_value=mock_conn), \
             patch('your_module.adapters.logger'):
            
            adapter.initialize_schema()
            
            # Verify all SQL operations were executed
            # ALTER, CREATE INDEX, CREATE FUNC, DROP TRIGGER, CREATE TRIGGER
            assert mock_cursor.execute.call_count == 5
            mock_conn.commit.assert_called_once()
            mock_conn.close.assert_called_once()

    def test_initialize_schema_failure_rollback(self, postgres_config):
        """Test schema initialization failure with rollback."""
        mock_conn = Mock()
        mock_cursor = Mock()
        mock_conn.cursor = Mock(return_value=mock_cursor)
        mock_cursor.__enter__ = Mock(return_value=mock_cursor)
        mock_cursor.__exit__ = Mock(return_value=False)
        mock_cursor.execute = Mock(side_effect=Exception("SQL error"))
        mock_conn.rollback = Mock()
        mock_conn.close = Mock()
        
        adapter = TsVectorChunkIndexerAdapter(
            config=postgres_config,
            language="english"
        )
        
        with patch.object(adapter, '_get_connection', return_value=mock_conn), \
             patch('your_module.adapters.logger'):
            
            with pytest.raises(Exception, match="SQL error"):
                adapter.initialize_schema()
            
            mock_conn.rollback.assert_called_once()
            mock_conn.close.assert_called_once()

    def test_initialize_schema_with_different_language(self, postgres_config):
        """Test schema initialization with different language."""
        mock_conn = Mock()
        mock_cursor = Mock()
        mock_conn.cursor = Mock(return_value=mock_cursor)
        mock_cursor.__enter__ = Mock(return_value=mock_cursor)
        mock_cursor.__exit__ = Mock(return_value=False)
        mock_conn.commit = Mock()
        mock_conn.close = Mock()
        
        adapter = TsVectorChunkIndexerAdapter(
            config=postgres_config,
            language="spanish"
        )
        
        with patch.object(adapter, '_get_connection', return_value=mock_conn), \
             patch('your_module.adapters.logger'):
            
            adapter.initialize_schema()
            
            assert adapter.language == "spanish"
            assert mock_cursor.execute.call_count == 5

    @pytest.mark.asyncio
    async def test_search_success(self, postgres_config, sample_documents):
        """Test successful search operation."""
        mock_conn = Mock()
        mock_cursor = Mock()
        mock_conn.cursor = Mock(return_value=mock_cursor)
        mock_cursor.__enter__ = Mock(return_value=mock_cursor)
        mock_cursor.__exit__ = Mock(return_value=False)
        mock_conn.close = Mock()
        
        # Mock search results
        mock_cursor.fetchall = Mock(return_value=[
            {
                "document": sample_documents[0].page_content,
                "cmetadata": sample_documents[0].metadata,
                "score": 0.95
            },
            {
                "document": sample_documents[1].page_content,
                "cmetadata": sample_documents[1].metadata,
                "score": 0.85
            }
        ])
        
        adapter = TsVectorChunkIndexerAdapter(
            config=postgres_config,
            language="english"
        )
        
        with patch.object(adapter, '_get_connection', return_value=mock_conn), \
             patch('your_module.adapters.logger'):
            
            query = SearchQuery(text="test search")
            results = await adapter.search(query, max_k=5)
            
            assert len(results) == 2
            assert isinstance(results[0], QueryResponse)
            assert results[0].score == 0.95
            assert results[1].score == 0.85
            mock_cursor.execute.assert_called_once()
            mock_conn.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_search_with_no_results(self, postgres_config):
        """Test search when no results are found."""
        mock_conn = Mock()
        mock_cursor = Mock()
        mock_conn.cursor = Mock(return_value=mock_cursor)
        mock_cursor.__enter__ = Mock(return_value=mock_cursor)
        mock_cursor.__exit__ = Mock(return_value=False)
        mock_cursor.fetchall = Mock(return_value=[])
        mock_conn.close = Mock()
        
        adapter = TsVectorChunkIndexerAdapter(
            config=postgres_config,
            language="english"
        )
        
        with patch.object(adapter, '_get_connection', return_value=mock_conn), \
             patch('your_module.adapters.logger'):
            
            query = SearchQuery(text="nonexistent")
            results = await adapter.search(query, max_k=10)
            
            assert results == []

    @pytest.mark.asyncio
    async def test_search_failure_exception(self, postgres_config):
        """Test search failure when exception occurs."""
        mock_conn = Mock()
        mock_cursor = Mock()
        mock_conn.cursor = Mock(return_value=mock_cursor)
        mock_cursor.__enter__ = Mock(return_value=mock_cursor)
        mock_cursor.__exit__ = Mock(return_value=False)
        mock_cursor.execute = Mock(side_effect=Exception("Database error"))
        mock_conn.close = Mock()
        
        adapter = TsVectorChunkIndexerAdapter(
            config=postgres_config,
            language="english"
        )
        
        with patch.object(adapter, '_get_connection', return_value=mock_conn), \
             patch('your_module.adapters.logger'):
            
            query = SearchQuery(text="test")
            results = await adapter.search(query, max_k=5)
            
            assert results == []
            mock_conn.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_search_with_special_characters(self, postgres_config):
        """Test search with special characters in query."""
        mock_conn = Mock()
        mock_cursor = Mock()
        mock_conn.cursor = Mock(return_value=mock_cursor)
        mock_cursor.__enter__ = Mock(return_value=mock_cursor)
        mock_cursor.__exit__ = Mock(return_value=False)
        mock_cursor.fetchall = Mock(return_value=[])
        mock_conn.close = Mock()
        
        adapter = TsVectorChunkIndexerAdapter(
            config=postgres_config,
            language="english"
        )
        
        with patch.object(adapter, '_get_connection', return_value=mock_conn), \
             patch('your_module.adapters.logger'):
            
            query = SearchQuery(text="test & query | with 'special' chars")
            results = await adapter.search(query, max_k=10)
            
            # Verify the query was executed (even with special chars)
            mock_cursor.execute.assert_called_once()
            call_args = mock_cursor.execute.call_args
            assert query.text in call_args[0][1]

    @pytest.mark.asyncio
    async def test_search_score_conversion(self, postgres_config):
        """Test that scores are properly converted to float."""
        mock_conn = Mock()
        mock_cursor = Mock()
        mock_conn.cursor = Mock(return_value=mock_cursor)
        mock_cursor.__enter__ = Mock(return_value=mock_cursor)
        mock_cursor.__exit__ = Mock(return_value=False)
        mock_conn.close = Mock()
        
        # Mock results with different score types
        mock_cursor.fetchall = Mock(return_value=[
            {
                "document": "Doc 1",
                "cmetadata": {"doc_id": "doc1"},
                "score": "0.95"  # String score
            },
            {
                "document": "Doc 2",
                "cmetadata": {"doc_id": "doc2"},
                "score": None  # None score
            }
        ])
        
        adapter = TsVectorChunkIndexerAdapter(
            config=postgres_config,
            language="english"
        )
        
        with patch.object(adapter, '_get_connection', return_value=mock_conn), \
             patch('your_module.adapters.logger'):
            
            query = SearchQuery(text="test")
            results = await adapter.search(query, max_k=5)
            
            # Verify scores were converted properly
            assert len(results) == 2
            assert isinstance(results[0].score, float)
            assert results[0].score == 0.95
            assert results[1].score == 0.0

    def test_get_connection_success(self, postgres_config):
        """Test successful database connection creation."""
        adapter = TsVectorChunkIndexerAdapter(
            config=postgres_config,
            language="english"
        )
        
        with patch('your_module.adapters.psycopg2.connect') as mock_connect:
            mock_connect.return_value = Mock()
            
            conn = adapter._get_connection()
            
            assert conn is not None
            mock_connect.assert_called_once()
            # Verify the connection string is properly formatted
            call_args = mock_connect.call_args[0][0]
            assert "postgresql://" in call_args
            assert "+psycopg" not in call_args

    def test_get_connection_failure(self, postgres_config):
        """Test database connection failure."""
        adapter = TsVectorChunkIndexerAdapter(
            config=postgres_config,
            language="english"
        )
        
        with patch('your_module.adapters.psycopg2.connect', 
                   side_effect=Exception("Connection failed")):
            
            with pytest.raises(Exception, match="Connection failed"):
                adapter._get_connection()

    @pytest.mark.asyncio
    async def test_select_not_implemented(self, postgres_config):
        """Test that select operation is a pass-through."""
        adapter = TsVectorChunkIndexerAdapter(
            config=postgres_config,
            language="english"
        )
        
        # Should not raise any exception
        filter_clauses = []
        result = await adapter.select(filter_clauses)
        assert result is None


# ============================================================================
# HELPER METHOD TESTS
# ============================================================================

class TestBaseChunkIndexerPort:
    """Test base adapter helper methods."""
    
    def test_document_to_chunk_conversion(self, sample_documents):
        """Test Document to DocumentChunk conversion."""
        document = sample_documents[0]
        
        chunk = BM25ChunkIndexerAdapter._document_to_chunk(document)
        
        assert isinstance(chunk, DocumentChunk)
        assert chunk.key == document.page_content
        assert chunk.content == document.metadata.get("content", "")
        assert chunk.document_id == document.metadata.get("document_id", "")

    def test_create_query_response(self, sample_documents):
        """Test QueryResponse creation from document and score."""
        document = sample_documents[0]
        score = 0.85
        
        response = BM25ChunkIndexerAdapter.create_query_response(document, score)
        
        assert isinstance(response, QueryResponse)
        assert response.score == score
        assert response.chunk.key == document.page_content
        assert response.metadata == document.metadata


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
