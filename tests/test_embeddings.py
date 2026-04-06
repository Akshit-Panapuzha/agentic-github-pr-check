import pytest
from unittest.mock import AsyncMock, MagicMock
from reviewer.embeddings import cosine_similarity, chunk_file_content, rank_chunks_by_relevance


def test_cosine_similarity_identical_vectors():
    v = [1.0, 0.0, 0.0]
    assert cosine_similarity(v, v) == pytest.approx(1.0)


def test_cosine_similarity_orthogonal_vectors():
    a = [1.0, 0.0]
    b = [0.0, 1.0]
    assert cosine_similarity(a, b) == pytest.approx(0.0)


def test_chunk_file_content_splits_into_overlapping_chunks():
    lines = [f"line {i}" for i in range(100)]
    content = "\n".join(lines)
    chunks = chunk_file_content(content, chunk_size=20, overlap=5)
    assert len(chunks) > 1
    first_chunk_lines = chunks[0].split("\n")
    assert len(first_chunk_lines) == 20


def test_chunk_file_content_short_file_returns_single_chunk():
    content = "line 1\nline 2\nline 3"
    chunks = chunk_file_content(content, chunk_size=20, overlap=5)
    assert len(chunks) == 1
    assert chunks[0] == content


async def test_rank_chunks_by_relevance_returns_within_token_budget():
    mock_client = AsyncMock()
    mock_client.embeddings.create.return_value = MagicMock(
        data=[
            MagicMock(embedding=[1.0, 0.0]),  # query
            MagicMock(embedding=[0.9, 0.1]),  # chunk 0 — most similar
            MagicMock(embedding=[0.0, 1.0]),  # chunk 1 — least similar
            MagicMock(embedding=[0.8, 0.2]),  # chunk 2 — second most similar
        ]
    )
    chunks = ["a " * 100, "b " * 100, "c " * 100]
    result = await rank_chunks_by_relevance(mock_client, "query text", chunks, token_budget=60)
    assert len(result) >= 1
    assert result[0] == chunks[0]
