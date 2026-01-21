class TestBM25ChunkIndexerAdapter:
    
    @pytest.fixture
    def mock_bm25_db(self):
        return AsyncMock(spec=Bm25InMemoryDatabase)

    @pytest.fixture
    def adapter(self, mock_bm25_db):
        config = Configuration()
        return BM25ChunkIndexerAdapter(
            configuration=config,
            language="english",
            bm25_db=mock_bm25_db
        )

    @pytest.mark.asyncio
    async def test_search_success(self, adapter, mock_bm25_db):
        """Test success case for BM25 search."""
        # Setup
        query = SearchQuery(text="test query")
        expected_responses = [
            QueryResponse(
                chunk=DocumentChunk(key="res1", content="c1"), 
                score=0.9, 
                metadata={}
            )
        ]
        mock_bm25_db.search.return_value = expected_responses

        # Execute
        results = await adapter.search(query, max_k=5)

        # Assert
        assert len(results) == 1
        assert results[0].score == 0.9
        mock_bm25_db.search.assert_called_once_with("test query", k=5)

    @pytest.mark.asyncio
    async def test_search_fail_exception_handling(self, adapter, mock_bm25_db):
        """Test fail case where underlying DB raises exception."""
        # Setup
        query = SearchQuery(text="break me")
        mock_bm25_db.search.side_effect = Exception("BM25 Crash")

        # Execute
        with patch("your_module.logger") as mock_logger: # Mocking the logger inside the module
            results = await adapter.search(query)

            # Assert
            assert results == []  # Should return empty list on failure as per code
            mock_logger.error.assert_called_once()
            assert "BM25 search failed" in mock_logger.error.call_args[0][0]

    @pytest.mark.asyncio
    async def test_from_documents_success(self):
        """Test factory method from_documents."""
        config = Configuration()
        cos_api = MagicMock()
        
        # Mock external dependencies
        with patch("your_module.v_cos_patch", return_value="v1_patch"), \
             patch.object(BM25ChunkIndexerAdapter, "_read_parsed_documents_from_cos") as mock_read, \
             patch("your_module.DocumentSplitter") as MockSplitter, \
             patch("your_module.Bm25InMemoryDatabase") as MockDb:

            # Setup Mocks
            mock_read.return_value = {"source1": [Document(page_content="doc1")]}
            
            mock_splitter_instance = MockSplitter.return_value
            mock_splitter_instance.split_documents = AsyncMock(return_value=[
                DocumentChunk(key="chunk1", content="c1")
            ])
            
            MockDb.from_documents.return_value = MagicMock()

            # Execute
            adapter = await BM25ChunkIndexerAdapter.from_documents(
                configuration=config,
                language="english",
                cos_bucket_api=cos_api
            )

            # Assert
            assert isinstance(adapter, BM25ChunkIndexerAdapter)
            MockDb.from_documents.assert_called_once()
            mock_splitter_instance.split_documents.assert_called_once()

    def test_from_saved_index_fail_not_found(self):
        """Test fail case where index does not exist on COS."""
        config = Configuration()
        cos_api = MagicMock()

        with patch.object(BM25ChunkIndexerAdapter, "_v_cos_patch", return_value="v1"), \
             patch.object(BM25ChunkIndexerAdapter, "_get_cos_bm25_directory", return_value="path/to/db"), \
             patch.object(BM25ChunkIndexerAdapter, "_bm25_exists_on_cos", return_value=False):
            
            # Execute & Assert
            with pytest.raises(FileNotFoundError) as exc:
                BM25ChunkIndexerAdapter.from_saved_index(
                    configuration=config,
                    language="english",
                    cos_bucket_api=cos_api
                )
            assert "is not a valid BM25 backup" in str(exc.value)
