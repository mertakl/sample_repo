import pytest
from your_module import BM25ChunkIndexerAdapter
from your_models import SearchQuery


@pytest.mark.asyncio
async def test_bm25_search_success(bm25_adapter):
    query = SearchQuery(text="hello")

    results = await bm25_adapter.search(query, max_k=5)

    assert isinstance(results, list)


@pytest.mark.asyncio
async def test_bm25_search_failure_returns_empty(mocker, bm25_adapter):
    mocker.patch.object(
        bm25_adapter.bm25_db,
        "search",
        side_effect=RuntimeError("BM25 broken"),
    )

    query = SearchQuery(text="hello")
    results = await bm25_adapter.search(query)

    assert results == []
