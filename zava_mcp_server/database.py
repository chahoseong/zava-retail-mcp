"""승인된 매장의 상품별 매출을 집계한다."""

from decimal import Decimal

from .models import ProductSales, SalesQuery
from .runtime import Pool

TOP_PRODUCTS_SQL = """
SELECT p.product_id, p.product_name, sum(i.total_amount) AS total_amount
FROM retail.orders AS o
JOIN retail.order_items AS i
    ON i.order_id = o.order_id AND i.store_id = o.store_id
JOIN retail.products AS p ON p.product_id = i.product_id
WHERE o.store_id = $1 AND o.order_date BETWEEN $2 AND $3
GROUP BY p.product_id, p.product_name
ORDER BY total_amount DESC, p.product_id ASC
LIMIT $4
"""


class SalesQueryError(RuntimeError):
    """원본 DB 오류를 숨기는 매출 조회 실패."""


class SalesQueryTimeoutError(SalesQueryError):
    """매출 조회의 연결 대여, 쿼리 또는 정리 시간 초과."""


class SalesRepository:
    def __init__(self, pool: Pool, acquire_timeout: float) -> None:
        self._pool = pool
        self._acquire_timeout = acquire_timeout

    async def top_products(self, query: SalesQuery) -> list[ProductSales]:
        """인가를 통과한 조건을 사용하고, 연결 반환 후 결과를 제공한다."""
        results = []
        try:
            async with self._pool.acquire(timeout=self._acquire_timeout) as connection:
                async with connection.transaction(readonly=True):
                    await connection.fetchval(
                        "SELECT set_config('app.current_store_id', $1, true)",
                        str(query.store_id),
                    )
                    rows = await connection.fetch(
                        TOP_PRODUCTS_SQL,
                        query.store_id,
                        query.start_date,
                        query.end_date,
                        query.limit,
                    )
                    for row in rows:
                        product_id = row["product_id"]
                        product_name = row["product_name"]
                        total_amount = row["total_amount"]
                        if (
                            type(product_id) is not int
                            or not isinstance(product_name, str)
                            or not isinstance(total_amount, Decimal)
                        ):
                            raise SalesQueryError(
                                "상품 매출 결과의 자료형이 올바르지 않습니다"
                            )
                        results.append(
                            ProductSales(product_id, product_name, total_amount)
                        )
        except TimeoutError:
            raise SalesQueryTimeoutError("매출 조회 중 시간이 초과되었습니다") from None
        except Exception:
            raise SalesQueryError("상품별 매출을 조회하지 못했습니다") from None
        return results
