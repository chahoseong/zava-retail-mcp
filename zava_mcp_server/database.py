"""승인된 매장의 매출을 집계한다."""

from collections.abc import AsyncGenerator
from contextlib import AsyncExitStack, asynccontextmanager
from decimal import Decimal

from anyio import CancelScope

from .models import ProductSales, SalesQuery, SalesSummary, SalesSummaryQuery
from .models import SalesQueryError as SalesQueryError
from .models import SalesQueryTimeoutError as SalesQueryTimeoutError
from .runtime import Connection, Pool

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

SALES_SUMMARY_SQL = """
SELECT COUNT(DISTINCT o.order_id) AS order_count,
       COALESCE(SUM(i.total_amount), 0) AS total_sales
FROM retail.orders AS o
LEFT JOIN retail.order_items AS i
    ON i.order_id = o.order_id AND i.store_id = o.store_id
WHERE o.store_id = $1 AND o.order_date BETWEEN $2 AND $3
"""


@asynccontextmanager
async def open_store_connection(
    pool: Pool, acquire_timeout: float, store_id: int
) -> AsyncGenerator[Connection, None]:
    """승인된 매장으로 범위를 제한한 읽기 전용 연결을 제공한다."""
    with CancelScope() as cleanup:
        async with AsyncExitStack() as resources:
            try:
                connection = await resources.enter_async_context(
                    pool.acquire(timeout=acquire_timeout)
                )
                await resources.enter_async_context(
                    connection.transaction(readonly=True)
                )
                await connection.fetchval(
                    "SELECT set_config('app.current_store_id', $1, true)", str(store_id)
                )
                yield connection
            finally:
                # 취소는 조회에 전달하고 트랜잭션 종료와 풀 반환은 완료한다.
                cleanup.shield = True


class SalesRepository:
    def __init__(self, pool: Pool, acquire_timeout: float) -> None:
        self._pool = pool
        self._acquire_timeout = acquire_timeout

    async def top_products(self, query: SalesQuery) -> list[ProductSales]:
        """인가를 통과한 조건을 사용하고, 연결 반환 후 결과를 제공한다."""
        results = []
        async with self._store_connection(query.store_id) as connection:
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
                    raise SalesQueryError("상품 매출 결과의 자료형이 올바르지 않습니다")
                results.append(ProductSales(product_id, product_name, total_amount))
        return results

    async def sales_summary(self, query: SalesSummaryQuery) -> SalesSummary:
        """승인된 매장의 주문 건수와 매출 합계를 조회한다."""
        async with self._store_connection(query.store_id) as connection:
            (row,) = await connection.fetch(
                SALES_SUMMARY_SQL, query.store_id, query.start_date, query.end_date
            )
            total_sales = row["total_sales"]
            order_count = row["order_count"]
            if not isinstance(total_sales, Decimal) or type(order_count) is not int:
                raise SalesQueryError("매출 요약 결과의 자료형이 올바르지 않습니다")
            summary = SalesSummary(total_sales, order_count)
        return summary

    @asynccontextmanager
    async def _store_connection(
        self, store_id: int
    ) -> AsyncGenerator[Connection, None]:
        try:
            async with open_store_connection(
                self._pool, self._acquire_timeout, store_id
            ) as connection:
                yield connection
        except TimeoutError:
            raise SalesQueryTimeoutError("매출 조회 중 시간이 초과되었습니다") from None
        except Exception:
            raise SalesQueryError("매출을 조회하지 못했습니다") from None
