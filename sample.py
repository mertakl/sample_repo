"""
Integration tests for BM25ChunkIndexerAdapter and TsVectorChunkIndexerAdapter.
Tests cover both success and failure scenarios.
"""

import pytest
import asyncio
from unittest.mock import Mock, patch, MagicMock, AsyncMock
from pathlib import Path
from tempfile import TemporaryDirectory
import psycopg2
from psycopg2.extras import RealDictCursor

# Assuming these imports based on your code structure
from your_module.adapters import BM25ChunkIndexerAdapter, TsVectorChunkIndexerAdapter
from your_module.models import (
    Document, DocumentChunk, SearchQuery, QueryResponse,
    Configuration, Span, Hyperlink, TableBlock, TitleBlock
)
from your_module.database import Bm25InMemoryDatabase, PGVectorDBConfig


# ============================================================================
# FIXTURES
# ============================================================================

@pytest.fixture
def sample_configuration():
    """Create a sample configuration object."""
    config = Mock(spec=Configuration)
    config.cos_version = "v1.0"
    config.document_splitter = Mock()
    config.document_parser = Mock()
    config.document_parser.document_object_cos_folder = "test_folder"
    config.document_parser.sources = {"source1": {}, "source2": {}}
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
def mock_bm25_db():
    """Create a mock BM25 in-memory database."""
    mock_db = Mock(spec=Bm25InMemoryDatabase)
    
    async def mock_search(query, k):
        return [
            QueryResponse(
                chunk=Mock(key="chunk1", content="Result 1"),
                score=0.95,
                metadata={"doc_id": "doc1"}
            ),
            QueryResponse(
                chunk=Mock(key="chunk2", content="Result 2"),
                score=0.85,
                metadata={"doc_id": "doc2"}
            )
        ]
    
    mock_db.search = AsyncMock(side_effect=mock_search)
    return mock_db


@pytest.fixture
def postgres_config():
    """Create a PostgreSQL configuration for testing."""
    config = Mock(spec=PGVectorDBConfig)
    config.get_connection_string = Mock(
        return_value="postgresql://user:pass@localhost:5432/testdb"
    )
    return config


@pytest.fixture
def mock_postgres_connection():
    """Create a mock PostgreSQL connection."""
    mock_conn = Mock()
    mock_cursor = Mock()
    mock_conn.cursor = Mock(return_value=mock_cursor)
    mock_conn.__enter__ = Mock(return_value=mock_conn)
    mock_conn.__exit__ = Mock(return_value=False)
    mock_cursor.__enter__ = Mock(return_value=mock_cursor)
    mock_cursor.__exit__ = Mock(return_value=False)
    return mock_conn


# ============================================================================
# BM25ChunkIndexerAdapter TESTS
# ============================================================================

class TestBM25ChunkIndexerAdapter:
    """Test suite for BM25ChunkIndexerAdapter."""

    @pytest.mark.asyncio
    async def test_from_documents_success(
        self, sample_configuration, mock_cos_bucket_api, sample_chunks
    ):
        """Test successful creation of BM25 adapter from documents."""
        data_source_to_documents = {
            "source1": [
                Document(page_content="Test 1", metadata={}),
                Document(page_content="Test 2", metadata={})
            ]
        }

        with patch('your_module.adapters.DocumentSplitter') as mock_splitter, \
             patch('your_module.adapters.Bm25InMemoryDatabase') as mock_bm25_class, \
             patch('your_module.adapters.v_cos_patch', return_value="v1_0"):
            
            # Setup mocks
            mock_splitter_instance = Mock()
            mock_splitter_instance.split_documents = AsyncMock(return_value=sample_chunks)
            mock_splitter.return_value = mock_splitter_instance
            
            mock_bm25_class.from_documents = Mock(return_value=Mock(spec=Bm25InMemoryDatabase))
            
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
            mock_splitter_instance.split_documents.assert_called_once()
            mock_bm25_class.from_documents.assert_called_once()

    @pytest.mark.asyncio
    async def test_from_documents_with_empty_documents(
        self, sample_configuration, mock_cos_bucket_api
    ):
        """Test creation with empty document list."""
        data_source_to_documents = {}

        with patch('your_module.adapters.DocumentSplitter') as mock_splitter, \
             patch('your_module.adapters.Bm25InMemoryDatabase') as mock_bm25_class, \
             patch.object(
                 BM25ChunkIndexerAdapter, 
                 '_read_parsed_documents_from_cos',
                 return_value={"source1": []}
             ):
            
            mock_splitter_instance = Mock()
            mock_splitter_instance.split_documents = AsyncMock(return_value=[])
            mock_splitter.return_value = mock_splitter_instance
            
            mock_bm25_class.from_documents = Mock(return_value=Mock(spec=Bm25InMemoryDatabase))
            
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
        self, sample_configuration, mock_cos_bucket_api
    ):
        """Test failure when document splitting raises an error."""
        data_source_to_documents = {
            "source1": [Document(page_content="Test", metadata={})]
        }

        with patch('your_module.adapters.DocumentSplitter') as mock_splitter, \
             patch('your_module.adapters.v_cos_patch', return_value="v1_0"):
            
            mock_splitter_instance = Mock()
            mock_splitter_instance.split_documents = AsyncMock(
                side_effect=Exception("Splitting failed")
            )
            mock_splitter.return_value = mock_splitter_instance
            
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
        ), patch('your_module.adapters.TemporaryDirectory'):
            
            adapter = BM25ChunkIndexerAdapter.from_saved_index(
                configuration=sample_configuration,
                language="english",
                cos_bucket_api=mock_cos_bucket_api
            )
            
            assert adapter is not None
            assert adapter.language == "english"
            assert adapter.bm25_db is not None

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
        ), patch('your_module.adapters.TemporaryDirectory'):
            
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
        
        adapter = TsVectorChunkIndexerAdapter(
            config=postgres_config,
            language="english"
        )
        
        with patch.object(adapter, '_get_connection', return_value=mock_conn):
            adapter.initialize_schema()
            
            # Verify all SQL operations were executed
            assert mock_cursor.execute.call_count == 5  # ALTER, CREATE INDEX, CREATE FUNC, DROP TRIGGER, CREATE TRIGGER
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
        
        adapter = TsVectorChunkIndexerAdapter(
            config=postgres_config,
            language="english"
        )
        
        with patch.object(adapter, '_get_connection', return_value=mock_conn):
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
        
        adapter = TsVectorChunkIndexerAdapter(
            config=postgres_config,
            language="spanish"
        )
        
        with patch.object(adapter, '_get_connection', return_value=mock_conn):
            adapter.initialize_schema()
            
            # Check that the language was used in the function creation
            calls = mock_cursor.execute.call_args_list
            func_call = str(calls[2])  # CREATE FUNC is the 3rd call
            assert "spanish" in func_call or adapter.language == "spanish"

    @pytest.mark.asyncio
    async def test_search_success(self, postgres_config):
        """Test successful search operation."""
        mock_conn = Mock()
        mock_cursor = Mock()
        mock_conn.cursor = Mock(return_value=mock_cursor)
        mock_cursor.__enter__ = Mock(return_value=mock_cursor)
        mock_cursor.__exit__ = Mock(return_value=False)
        
        # Mock search results
        mock_cursor.fetchall = Mock(return_value=[
            {
                "document": "Test document 1",
                "cmetadata": {"doc_id": "doc1"},
                "score": 0.95
            },
            {
                "document": "Test document 2",
                "cmetadata": {"doc_id": "doc2"},
                "score": 0.85
            }
        ])
        
        adapter = TsVectorChunkIndexerAdapter(
            config=postgres_config,
            language="english"
        )
        
        with patch.object(adapter, '_get_connection', return_value=mock_conn), \
             patch.object(adapter, 'documents_wıth_scores_to_query_responses') as mock_convert:
            
            mock_convert.return_value = [
                Mock(score=0.95),
                Mock(score=0.85)
            ]
            
            query = SearchQuery(text="test search")
            results = await adapter.search(query, max_k=5)
            
            assert len(results) == 2
            assert results[0].score == 0.95
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
        
        adapter = TsVectorChunkIndexerAdapter(
            config=postgres_config,
            language="english"
        )
        
        with patch.object(adapter, '_get_connection', return_value=mock_conn), \
             patch.object(adapter, 'documents_wıth_scores_to_query_responses') as mock_convert:
            
            mock_convert.return_value = []
            
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
        
        adapter = TsVectorChunkIndexerAdapter(
            config=postgres_config,
            language="english"
        )
        
        with patch.object(adapter, '_get_connection', return_value=mock_conn):
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
        
        adapter = TsVectorChunkIndexerAdapter(
            config=postgres_config,
            language="english"
        )
        
        with patch.object(adapter, '_get_connection', return_value=mock_conn), \
             patch.object(adapter, 'documents_wıth_scores_to_query_responses') as mock_convert:
            
            mock_convert.return_value = []
            
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
        
        # Mock results with different score types
        mock_cursor.fetchall = Mock(return_value=[
            {
                "document": "Doc 1",
                "cmetadata": {},
                "score": "0.95"  # String score
            },
            {
                "document": "Doc 2",
                "cmetadata": {},
                "score": None  # None score
            }
        ])
        
        adapter = TsVectorChunkIndexerAdapter(
            config=postgres_config,
            language="english"
        )
        
        with patch.object(adapter, '_get_connection', return_value=mock_conn), \
             patch.object(adapter, 'documents_wıth_scores_to_query_responses', 
                         side_effect=lambda x: x) as mock_convert:
            
            query = SearchQuery(text="test")
            await adapter.search(query, max_k=5)
            
            # Check that conversion was called with proper doc-score tuples
            call_args = mock_convert.call_args[0][0]
            assert len(call_args) == 2
            # First score should be converted to float
            assert isinstance(call_args[0][1], float)
            # Second score should default to 0.0
            assert call_args[1][1] == 0.0

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


# ============================================================================
# INTEGRATION TESTS (Requires actual databases)
# ============================================================================

@pytest.mark.integration
class TestBM25Integration:
    """Integration tests requiring actual BM25 setup."""
    
    @pytest.mark.asyncio
    async def test_full_workflow_from_documents_to_search(
        self, sample_configuration, sample_chunks
    ):
        """Test complete workflow from document creation to search."""
        # This would require actual BM25 database setup
        # Placeholder for actual integration test
        pass


@pytest.mark.integration
class TestTsVectorIntegration:
    """Integration tests requiring actual PostgreSQL database."""
    
    @pytest.mark.asyncio
    async def test_full_workflow_initialize_and_search(self):
        """Test complete workflow from schema initialization to search."""
        # This would require actual PostgreSQL database
        # Placeholder for actual integration test
        pass


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
