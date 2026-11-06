"""상품 검색의 권한 검사와 임베딩·조회 순서를 관리한다."""

from typing import Protocol

from anyio import CapacityLimiter, to_thread

from .models import CATALOG_READ, ProductSearchInput, ProductSearchResults, UserContext
from .services import PermissionDeniedError


class ProductSearchUnavailableError(RuntimeError):
    """상품 검색 모델이 준비되지 않았다."""


class ProductSearchEmbeddingError(RuntimeError):
    """검색어를 임베딩하지 못했다."""


class ProductSearchQueryError(RuntimeError):
    """원본 DB 오류를 숨기는 상품 검색 조회 실패."""


class QueryEmbedder(Protocol):
    def embed_query(self, query: str) -> list[float]: ...


class ProductSearchReader(Protocol):
    async def search(
        self, store_id: int, vector: list[float], limit: int
    ) -> ProductSearchResults: ...


class ProductSearchService:
    def __init__(
        self, embedder: QueryEmbedder | None, repository: ProductSearchReader
    ) -> None:
        self._embedder = embedder
        self._repository = repository
        self._inference_limit = CapacityLimiter(1)

    async def search(
        self, user: UserContext, request: ProductSearchInput
    ) -> ProductSearchResults:
        if (
            CATALOG_READ not in user.allowed_actions
            or request.store_id not in user.allowed_store_ids
        ):
            raise PermissionDeniedError("요청한 매장의 상품 검색 권한이 없습니다")
        if self._embedder is None:
            raise ProductSearchUnavailableError("상품 검색 모델을 사용할 수 없습니다")
        try:
            vector = await to_thread.run_sync(
                self._embedder.embed_query, request.query, limiter=self._inference_limit
            )
        except Exception:
            raise ProductSearchEmbeddingError(
                "검색어를 임베딩하지 못했습니다"
            ) from None
        return await self._repository.search(request.store_id, vector, request.limit)
