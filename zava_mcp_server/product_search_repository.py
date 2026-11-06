"""승인된 매장의 취급 상품을 코사인 거리로 검색한다."""

import json

from .database import open_store_connection
from .models import ProductSearchResult, ProductSearchResults
from .product_search_service import ProductSearchQueryError
from .runtime import Pool

SEARCH_SQL = """
SELECT p.product_id, p.product_name, p.product_description,
       1 - (e.embedding <=> $2::text::vector) AS similarity_score
FROM retail.inventory AS i
JOIN retail.products AS p ON p.product_id = i.product_id
JOIN retail.product_embeddings AS e ON e.product_id = i.product_id
WHERE i.store_id = $1
ORDER BY e.embedding <=> $2::text::vector, p.product_id
LIMIT $3
"""


class ProductSearchRepository:
    def __init__(self, pool: Pool, acquire_timeout: float) -> None:
        self._pool = pool
        self._acquire_timeout = acquire_timeout

    async def search(
        self, store_id: int, vector: list[float], limit: int
    ) -> ProductSearchResults:
        try:
            encoded = json.dumps(vector, separators=(",", ":"), allow_nan=False)
            async with open_store_connection(
                self._pool, self._acquire_timeout, store_id
            ) as connection:
                rows = await connection.fetch(SEARCH_SQL, store_id, encoded, limit)
            return [ProductSearchResult.model_validate(dict(row)) for row in rows]
        except TimeoutError:
            raise ProductSearchQueryError(
                "상품 검색 조회 시간이 초과되었습니다"
            ) from None
        except Exception:
            raise ProductSearchQueryError(
                "데이터베이스에서 상품을 검색하지 못했습니다"
            ) from None
