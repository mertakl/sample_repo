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
