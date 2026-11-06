from contextlib import asynccontextmanager
from io import StringIO
from time import sleep
from unittest.mock import AsyncMock, Mock

import pytest
from rich.console import Console

from scripts import prepare_product_embeddings as command
from zava_mcp_server.embeddings import EMBEDDING_DIMENSION, EmbeddingAdapter

VECTOR = [1.0] + [0.0] * (EMBEDDING_DIMENSION - 1)


def encoder_returning(*vectors):
    return Mock(**{"encode.return_value.tolist.return_value": list(vectors)})


def test_document_and_query_use_the_same_encoder_with_distinct_inputs():
    encoder = encoder_returning(VECTOR)
    adapter = EmbeddingAdapter(encoder)
    assert adapter.embed_documents([("작업대", "접이식")]) == [VECTOR]
    encoder.encode.assert_called_once_with(
        ["title: 작업대 | text: 접이식"], prompt_name=None, show_progress_bar=False
    )
    encoder.reset_mock()
    assert adapter.embed_query("작업대") == VECTOR
    encoder.encode.assert_called_once_with(
        ["작업대"], prompt_name="SearchQuery", show_progress_bar=False
    )


@pytest.mark.parametrize(
    "vectors",
    [
        [],
        [VECTOR[:-1]],
        [[0.0] * EMBEDDING_DIMENSION],
        [[float("nan"), *VECTOR[1:]]],
        [[float("inf"), *VECTOR[1:]]],
    ],
)
def test_adapter_rejects_invalid_vectors(vectors):
    with pytest.raises(ValueError):
        EmbeddingAdapter(encoder_returning(*vectors)).embed_query("작업대")


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["log", "terminal", "failed_commit", "invalid_vector"])
async def test_prepare_reports_progress_and_only_announces_committed_storage(
    monkeypatch, mode
):
    reader = AsyncMock()
    reader.fetch.return_value = [
        {"product_id": 1, "product_name": "작업대", "product_description": "접이식"}
    ]
    writer = AsyncMock()
    connect = AsyncMock(side_effect=[reader, writer])
    monkeypatch.setattr(command, "connect", connect)
    output = StringIO()
    monkeypatch.setenv("TERM", "xterm")
    console = Console(
        file=output,
        force_terminal=mode == "terminal",
        force_interactive=mode == "terminal",
        legacy_windows=False,
        width=100,
        markup=False,
    )

    @asynccontextmanager
    async def transaction():
        yield
        assert "커밋 완료" not in output.getvalue()
        if mode == "failed_commit":
            raise OSError("commit failed")

    writer.transaction = transaction

    def encode(*args, **kwargs):
        reader.close.assert_awaited_once()
        connect.assert_awaited_once()
        if mode == "terminal":
            sleep(1.2)
            assert "0/1" in output.getvalue()
            assert "0:00:01" in output.getvalue()
        vectors = [VECTOR[:-1]] if mode == "invalid_vector" else [VECTOR]
        return Mock(tolist=lambda: vectors)

    monkeypatch.setattr(
        command.EmbeddingAdapter, "load", lambda: EmbeddingAdapter(Mock(encode=encode))
    )

    if mode in {"failed_commit", "invalid_vector"}:
        with pytest.raises(OSError if mode == "failed_commit" else ValueError):
            await command.prepare(None, console)
        assert "커밋 완료" not in output.getvalue()
        if mode == "invalid_vector":
            connect.assert_awaited_once()
            writer.executemany.assert_not_awaited()
        else:
            writer.close.assert_awaited_once()
        return

    await command.prepare(None, console)
    if mode == "log":
        assert "배치 1 완료 (1/1개)" in output.getvalue()
        assert "\x1b" not in output.getvalue()
    writer.executemany.assert_awaited_once()
    assert "커밋 완료" in output.getvalue()
