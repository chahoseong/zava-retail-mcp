"""상품과 검색어에 같은 EmbeddingGemma 2 리비전을 사용한다."""

from collections.abc import Sequence
from math import isfinite
from typing import Protocol, cast

MODEL_ID = "google/embeddinggemma-2"
MODEL_REVISION = "f9972ac22e696a105c482202646979e33e4b5a1e"
EMBEDDING_DIMENSION = 768


class _EmbeddingArray(Protocol):
    def tolist(self) -> list[list[float]]: ...


class _TextEncoder(Protocol):
    def encode(
        self, sentences: list[str], *, prompt_name: str | None, show_progress_bar: bool
    ) -> _EmbeddingArray: ...


class EmbeddingAdapter:
    def __init__(self, model: _TextEncoder) -> None:
        self._model = model

    @classmethod
    def load(cls) -> "EmbeddingAdapter":
        from sentence_transformers import SentenceTransformer

        model = SentenceTransformer(
            MODEL_ID,
            revision=MODEL_REVISION,
            config_kwargs={"vision_config": None, "audio_config": None},
        )
        return cls(cast(_TextEncoder, model))

    def embed_documents(
        self, documents: Sequence[tuple[str, str]]
    ) -> list[list[float]]:
        # 제목을 직접 넣어 기본 Document 프롬프트의 title: none을 대체한다.
        return self._encode(
            [
                f"title: {title} | text: {description}"
                for title, description in documents
            ],
            prompt_name=None,
        )

    def embed_query(self, query: str) -> list[float]:
        (vector,) = self._encode([query], prompt_name="SearchQuery")
        return vector

    def _encode(
        self, texts: list[str], *, prompt_name: str | None
    ) -> list[list[float]]:
        if not texts:
            return []
        vectors = self._model.encode(
            texts, prompt_name=prompt_name, show_progress_bar=False
        ).tolist()
        if len(vectors) != len(texts):
            raise ValueError("입력 수와 임베딩 수가 일치하지 않습니다.")
        for vector in vectors:
            if (
                len(vector) != EMBEDDING_DIMENSION
                or not all(isfinite(value) for value in vector)
                or not any(vector)
            ):
                raise ValueError(
                    "임베딩은 유한한 값으로 구성된 768차원 비영벡터여야 합니다."
                )
        return vectors
