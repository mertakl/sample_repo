"""
Integration tests for BM25ChunkIndexerAdapter and TsVectorChunkIndexerAdapter
"""
import pytest
from unittest.mock import Mock, patch, AsyncMock
from langchain.schema import Document
import tempfile
from pathlib import Path

from your_module.adapters import (
    BM25ChunkIndexerAdapter,
    TsVectorChunkIndexerAdapter,
)
from your_module.models import (
    DocumentChunk,
    SearchQuery,
    Span,
)


# ============================================================================
# BM25ChunkIndexerAdapter Integration Tests
# ============================================================================

@pytest.mark.asyncio
async def test_bm25_adapter_end_to_end_search(configuration, lexical_db):
    """Integration test: BM25 adapter full search workflow"""
    # Create adapter with real lexical_db fixture
    adapter = BM25ChunkIndexerAdapter(
        configuration=configuration,
        language="english",
        bm25_db=lexical_db,
        nb_retrieved_doc_factor=1,
    )
    
    # Perform search
    query = SearchQuery(text="test search query")
    results = await adapter.search(query, max_k=5)
    
    # Verify results structure
    assert isinstance(results, list)
    for result in results:
        assert hasattr(result, 'chunk')
        assert hasattr(result, 'score')
        assert hasattr(result, 'metadata')


@pytest.mark.asyncio
async def test_bm25_adapter_multiple_searches(configuration, lexical_db):
    """Integration test: Multiple consecutive searches"""
    adapter = BM25ChunkIndexerAdapter(
        configuration=configuration,
        language="english",
        bm25_db=lexical_db,
    )
    
    queries = [
        SearchQuery(text="first query"),
        SearchQuery(text="second query"),
        SearchQuery(text="third query"),
    ]
    
    all_results = []
    for query in queries:
        results = await adapter.search(query, max_k=3)
        all_results.append(results)
    
    assert len(all_results) == 3


@pytest.mark.asyncio
@patch('your_module.adapters.DocumentSplitter')
@patch('your_module.adapters.Bm25InMemoryDatabase')
async def test_bm25_from_documents_integration(
    mock_bm25_class, mock_splitter_class, configuration, cos_client
):
    """Integration test: Creating BM25 adapter from documents"""
    # Setup document splitter mock
    mock_splitter = Mock()
    mock_chunks = [
        DocumentChunk(
            key=f"chunk_{i}",
            content=f"Content {i}",
            document_id=f"doc_{i}",
            span_in_document=Span(start=i*100, end=(i+1)*100),
            hyperlinks=[],
            tables=[],
            header_ancestry=[],
            headers_before=[],
            metadata={},
        )
        for i in range(5)
    ]
    mock_splitter.split_documents = AsyncMock(return_value=mock_chunks)
    mock_splitter_class.return_value = mock_splitter
    
    # Setup BM25 database mock
    mock_bm25_db = Mock()
    mock_bm25_class.from_documents.return_value = mock_bm25_db
    
    # Prepare test documents
    test_documents = {
        "source1": [
            Document(page_content="Document 1", metadata={"id": "1"}),
            Document(page_content="Document 2", metadata={"id": "2"}),
        ],
        "source2": [
            Document(page_content="Document 3", metadata={"id": "3"}),
        ]
    }
    
    # Mock the static methods
    with patch.object(
        BM25ChunkIndexerAdapter,
        '_read_parsed_documents_from_cos',
        return_value=test_documents
    ):
        adapter = await BM25ChunkIndexerAdapter.from_documents(
            configuration=configuration,
            language="english",
            cos_bucket_api=cos_client,
            data_source_to_documents=test_documents,
            nb_retrieved_doc_factor=1,
        )
    
    # Verify adapter was created correctly
    assert adapter.language == "english"
    assert adapter.nb_retrieved_doc_factor == 1
    mock_splitter.split_documents.assert_called_once()
    mock_bm25_class.from_documents.assert_called_once_with(
        mock_chunks,
        nb_retrieved_doc_factor=1
    )


@pytest.mark.asyncio
async def test_bm25_from_documents_with_cos_reading(configuration, cos_client):
    """Integration test: BM25 adapter reads from COS when no documents provided"""
    mock_documents = {
        "source1": [Document(page_content="COS doc", metadata={})]
    }
    
    with patch.object(
        BM25ChunkIndexerAdapter,
        '_read_parsed_documents_from_cos',
        return_value=mock_documents
    ), patch('your_module.adapters.DocumentSplitter') as mock_splitter_class, \
       patch('your_module.adapters.Bm25InMemoryDatabase') as mock_bm25_class:
        
        mock_splitter = Mock()
        mock_splitter.split_documents = AsyncMock(return_value=[])
        mock_splitter_class.return_value = mock_splitter
        
        mock_bm25_db = Mock()
        mock_bm25_class.from_documents.return_value = mock_bm25_db
        
        adapter = await BM25ChunkIndexerAdapter.from_documents(
            configuration=configuration,
            language="english",
            cos_bucket_api=cos_client,
            data_source_to_documents=None,  # Should trigger COS reading
            nb_retrieved_doc_factor=1,
        )
        
        # Verify COS reading was called
        BM25ChunkIndexerAdapter._read_parsed_documents_from_cos.assert_called_once()


@pytest.mark.asyncio
async def test_bm25_from_saved_index_integration(configuration, cos_client):
    """Integration test: Loading BM25 index from COS"""
    with patch.object(
        BM25ChunkIndexerAdapter,
        '_bm25_exists_on_cos',
        return_value=True
    ), patch.object(
        BM25ChunkIndexerAdapter,
        '_get_cos_bm25_directory',
        return_value='test/path/bm25'
    ), patch.object(
        BM25ChunkIndexerAdapter,
        '_download_bm25_files'
    ) as mock_download, patch('your_module.adapters.Bm25InMemoryDatabase') as mock_bm25_class:
        
        mock_bm25_db = Mock()
        mock_bm25_class.load.return_value = mock_bm25_db
        
        adapter = BM25ChunkIndexerAdapter.from_saved_index(
            configuration=configuration,
            language="french",
            cos_bucket_api=cos_client,
        )
        
        # Verify the workflow
        assert adapter.language == "french"
        mock_download.assert_called_once()
        mock_bm25_class.load.assert_called_once()


@pytest.mark.asyncio
async def test_bm25_download_files_creates_local_copies(configuration, cos_client):
    """Integration test: Downloading BM25 files creates local copies"""
    # Mock file listing
    cos_client.list_files_in_bucket_folder.return_value = [
        "bm25/index.pkl",
        "bm25/metadata.json",
    ]
    
    downloaded_files = []
    
    def mock_download(cos_filename, local_filename):
        downloaded_files.append(local_filename)
        # Create empty file to simulate download
        Path(local_filename).touch()
    
    cos_client.download_file.side_effect = mock_download
    
    with tempfile.TemporaryDirectory() as tmp_dir:
        BM25ChunkIndexerAdapter._download_bm25_files(
            cos_bucket_api=cos_client,
            path_to_database="bm25",
            tmp_dir_name=tmp_dir,
            configuration=configuration,
        )
        
        # Verify files were downloaded
        assert len(downloaded_files) == 2
        for file_path in downloaded_files:
            assert Path(file_path).exists()


# ============================================================================
# TsVectorChunkIndexerAdapter Integration Tests (with pytest-postgresql)
# ============================================================================

pytest_plugins = ['pytest_postgresql']


@pytest.fixture
def pg_config():
    """PostgreSQL configuration for tests"""
    return Mock(
        get_connection_string=Mock(
            return_value="postgresql+psycopg://test:test@localhost:5432/test_db"
        )
    )


@pytest.mark.asyncio
async def test_tsvector_schema_initialization_integration(postgresql):
    """Integration test: TsVector schema initialization on real database"""
    import psycopg2
    from psycopg2.extras import RealDictCursor
    
    # Get connection info from postgresql fixture
    conn_info = postgresql.info
    conn_string = f"postgresql://{conn_info.user}@{conn_info.host}:{conn_info.port}/{conn_info.dbname}"
    
    mock_config = Mock()
    mock_config.get_connection_string.return_value = f"postgresql+psycopg://{conn_info.user}@{conn_info.host}:{conn_info.port}/{conn_info.dbname}"
    
    # Create table first
    conn = psycopg2.connect(
        host=conn_info.host,
        port=conn_info.port,
        dbname=conn_info.dbname,
        user=conn_info.user
    )
    
    try:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE SCHEMA IF NOT EXISTS aisc_ap04;
                CREATE TABLE IF NOT EXISTS aisc_ap04.langchain_pg_embedding (
                    id SERIAL PRIMARY KEY,
                    document TEXT,
                    cmetadata JSONB
                );
            """)
        conn.commit()
        
        # Create adapter and initialize schema
        adapter = TsVectorChunkIndexerAdapter(
            config=mock_config,
            language="english",
            table_name="aisc_ap04.langchain_pg_embedding"
        )
        
        adapter.initialize_schema()
        
        # Verify schema was created
        with conn.cursor() as cur:
            # Check if column was added
            cur.execute("""
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_schema = 'aisc_ap04' 
                AND table_name = 'langchain_pg_embedding' 
                AND column_name = 'document_tsvector'
            """)
            result = cur.fetchone()
            assert result is not None
            
            # Check if index exists
            cur.execute("""
                SELECT indexname 
                FROM pg_indexes 
                WHERE schemaname = 'aisc_ap04' 
                AND tablename = 'langchain_pg_embedding' 
                AND indexname = 'idx_document_tsvector'
            """)
            result = cur.fetchone()
            assert result is not None
            
            # Check if trigger exists
            cur.execute("""
                SELECT tgname 
                FROM pg_trigger 
                WHERE tgname = 'tsvector_update'
            """)
            result = cur.fetchone()
            assert result is not None
            
    finally:
        conn.close()


@pytest.mark.asyncio
async def test_tsvector_search_integration(postgresql):
    """Integration test: Full TsVector search on real database"""
    import psycopg2
    
    # Get connection info
    conn_info = postgresql.info
    
    mock_config = Mock()
    mock_config.get_connection_string.return_value = f"postgresql+psycopg://{conn_info.user}@{conn_info.host}:{conn_info.port}/{conn_info.dbname}"
    
    # Setup database
    conn = psycopg2.connect(
        host=conn_info.host,
        port=conn_info.port,
        dbname=conn_info.dbname,
        user=conn_info.user
    )
    
    try:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE SCHEMA IF NOT EXISTS aisc_ap04;
                CREATE TABLE IF NOT EXISTS aisc_ap04.langchain_pg_embedding (
                    id SERIAL PRIMARY KEY,
                    document TEXT,
                    cmetadata JSONB,
                    document_tsvector tsvector
                );
            """)
        conn.commit()
        
        # Create adapter and initialize
        adapter = TsVectorChunkIndexerAdapter(
            config=mock_config,
            language="english",
            table_name="aisc_ap04.langchain_pg_embedding"
        )
        
        adapter.initialize_schema()
        
        # Insert test data
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO aisc_ap04.langchain_pg_embedding (document, cmetadata)
                VALUES 
                    ('Python is a programming language', '{"doc_id": "1"}'),
                    ('JavaScript is used for web development', '{"doc_id": "2"}'),
                    ('Machine learning with Python is powerful', '{"doc_id": "3"}')
            """)
        conn.commit()
        
        # Perform search
        query = SearchQuery(text="Python programming")
        results = await adapter.search(query, max_k=5)
        
        # Verify results
        assert len(results) > 0
        assert any('Python' in result.chunk.key for result in results)
        
        # Verify scores are present and valid
        for result in results:
            assert result.score >= 0.0
            
    finally:
        conn.close()


@pytest.mark.asyncio
async def test_tsvector_search_no_results_integration(postgresql):
    """Integration test: TsVector search with no matching results"""
    import psycopg2
    
    conn_info = postgresql.info
    
    mock_config = Mock()
    mock_config.get_connection_string.return_value = f"postgresql+psycopg://{conn_info.user}@{conn_info.host}:{conn_info.port}/{conn_info.dbname}"
    
    conn = psycopg2.connect(
        host=conn_info.host,
        port=conn_info.port,
        dbname=conn_info.dbname,
        user=conn_info.user
    )
    
    try:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE SCHEMA IF NOT EXISTS aisc_ap04;
                CREATE TABLE IF NOT EXISTS aisc_ap04.langchain_pg_embedding (
                    id SERIAL PRIMARY KEY,
                    document TEXT,
                    cmetadata JSONB,
                    document_tsvector tsvector
                );
            """)
        conn.commit()
        
        adapter = TsVectorChunkIndexerAdapter(
            config=mock_config,
            language="english",
            table_name="aisc_ap04.langchain_pg_embedding"
        )
        
        adapter.initialize_schema()
        
        # Search without any data
        query = SearchQuery(text="nonexistent term xyz")
        results = await adapter.search(query, max_k=10)
        
        assert len(results) == 0
        
    finally:
        conn.close()


@pytest.mark.asyncio
async def test_tsvector_different_languages_integration(postgresql):
    """Integration test: TsVector with different language configurations"""
    import psycopg2
    
    conn_info = postgresql.info
    
    for language in ['english', 'french', 'german']:
        mock_config = Mock()
        mock_config.get_connection_string.return_value = f"postgresql+psycopg://{conn_info.user}@{conn_info.host}:{conn_info.port}/{conn_info.dbname}"
        
        conn = psycopg2.connect(
            host=conn_info.host,
            port=conn_info.port,
            dbname=conn_info.dbname,
            user=conn_info.user
        )
        
        try:
            table_name = f"aisc_ap04.test_{language}"
            
            with conn.cursor() as cur:
                cur.execute(f"""
                    CREATE SCHEMA IF NOT EXISTS aisc_ap04;
                    DROP TABLE IF EXISTS {table_name};
                    CREATE TABLE {table_name} (
                        id SERIAL PRIMARY KEY,
                        document TEXT,
                        cmetadata JSONB,
                        document_tsvector tsvector
                    );
                """)
            conn.commit()
            
            adapter = TsVectorChunkIndexerAdapter(
                config=mock_config,
                language=language,
                table_name=table_name
            )
            
            # Should not raise an error
            adapter.initialize_schema()
            
            # Verify trigger function uses correct language
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT prosrc FROM pg_proc 
                    WHERE proname = 'document_tsvector_trigger'
                """)
                result = cur.fetchone()
                assert result is not None
                assert language in result[0]
                
        finally:
            conn.close()


@pytest.mark.asyncio
async def test_tsvector_max_k_parameter_integration(postgresql):
    """Integration test: TsVector respects max_k parameter"""
    import psycopg2
    
    conn_info = postgresql.info
    
    mock_config = Mock()
    mock_config.get_connection_string.return_value = f"postgresql+psycopg://{conn_info.user}@{conn_info.host}:{conn_info.port}/{conn_info.dbname}"
    
    conn = psycopg2.connect(
        host=conn_info.host,
        port=conn_info.port,
        dbname=conn_info.dbname,
        user=conn_info.user
    )
    
    try:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE SCHEMA IF NOT EXISTS aisc_ap04;
                CREATE TABLE IF NOT EXISTS aisc_ap04.langchain_pg_embedding (
                    id SERIAL PRIMARY KEY,
                    document TEXT,
                    cmetadata JSONB,
                    document_tsvector tsvector
                );
            """)
        conn.commit()
        
        adapter = TsVectorChunkIndexerAdapter(
            config=mock_config,
            language="english",
            table_name="aisc_ap04.langchain_pg_embedding"
        )
        
        adapter.initialize_schema()
        
        # Insert multiple documents
        with conn.cursor() as cur:
            for i in range(20):
                cur.execute("""
                    INSERT INTO aisc_ap04.langchain_pg_embedding (document, cmetadata)
                    VALUES (%s, %s)
                """, (f"Test document number {i}", f'{{"doc_id": "{i}"}}'))
        conn.commit()
        
        # Search with different max_k values
        query = SearchQuery(text="Test document")
        
        results_3 = await adapter.search(query, max_k=3)
        results_5 = await adapter.search(query, max_k=5)
        results_10 = await adapter.search(query, max_k=10)
        
        assert len(results_3) <= 3
        assert len(results_5) <= 5
        assert len(results_10) <= 10
        
    finally:
        conn.close()


@pytest.mark.asyncio
async def test_tsvector_metadata_preservation_integration(postgresql):
    """Integration test: Verify metadata is preserved through search"""
    import psycopg2
    
    conn_info = postgresql.info
    
    mock_config = Mock()
    mock_config.get_connection_string.return_value = f"postgresql+psycopg://{conn_info.user}@{conn_info.host}:{conn_info.port}/{conn_info.dbname}"
    
    conn = psycopg2.connect(
        host=conn_info.host,
        port=conn_info.port,
        dbname=conn_info.dbname,
        user=conn_info.user
    )
    
    try:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE SCHEMA IF NOT EXISTS aisc_ap04;
                CREATE TABLE IF NOT EXISTS aisc_ap04.langchain_pg_embedding (
                    id SERIAL PRIMARY KEY,
                    document TEXT,
                    cmetadata JSONB,
                    document_tsvector tsvector
                );
            """)
        conn.commit()
        
        adapter = TsVectorChunkIndexerAdapter(
            config=mock_config,
            language="english",
            table_name="aisc_ap04.langchain_pg_embedding"
        )
        
        adapter.initialize_schema()
        
        # Insert with complex metadata
        test_metadata = {
            "doc_id": "test_123",
            "content": "Full content text",
            "document_id": "doc_xyz",
            "span_in_document": {"start": 0, "end": 100},
            "custom_field": "custom_value"
        }
        
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO aisc_ap04.langchain_pg_embedding (document, cmetadata)
                VALUES (%s, %s)
            """, ("Document with metadata", str(test_metadata).replace("'", '"')))
        conn.commit()
        
        # Search and verify metadata
        query = SearchQuery(text="Document metadata")
        results = await adapter.search(query, max_k=5)
        
        assert len(results) > 0
        result = results[0]
        assert result.metadata is not None
        
    finally:
        conn.close()
